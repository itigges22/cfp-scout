"""One conference table, plus per-person participation.

Drops ``past_conferences`` and moves what it was really carrying to where
it belongs:

  * The event-level facts (which edition, what we spent, how big it was,
    whether it was worth it) become columns on ``conferences``, because a
    conference we attended is a conference.
  * The ``attended_sme_ids`` / ``attended_by_names_raw`` array pair becomes
    the ``participation`` table — one row per person, per activity. The
    arrays could say "these five people went" but never "Alice gave the
    talk and Bob worked the booth", which was the thing the team most
    wanted to record.

No data is carried across. This is deliberate and agreed: the attendance
history is being re-entered by hand against the new model, so a best-effort
translation of the old rows would only produce records nobody trusts.

Revision ID: 20260725_1200
Revises: 20260725_1000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260725_1200"
down_revision = "20260725_1000"
branch_labels = None
depends_on = None

# Frozen copies. Migrations must not import from app/, or a later edit to
# the canonical list silently rewrites what this migration did.
_ACTIVITIES = ("talk", "booth", "attend", "sponsor")
_OUTCOMES = ("submitted", "accepted", "rejected", "delivered", "withdrawn")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # --- conferences absorbs the event-level attendance facts -------------
    op.add_column(
        "conferences",
        sa.Column("edition_year", sa.SmallInteger(), nullable=True),
        schema="app",
    )
    op.add_column(
        "conferences", sa.Column("spend_usd", sa.Integer(), nullable=True), schema="app"
    )
    op.add_column(
        "conferences",
        sa.Column("audience_size_estimate", sa.Integer(), nullable=True),
        schema="app",
    )
    op.add_column(
        "conferences",
        sa.Column("attendance_verdict", sa.String(length=20), nullable=True),
        schema="app",
    )
    op.add_column(
        "conferences",
        sa.Column(
            "attendance_notes", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
        schema="app",
    )
    op.create_check_constraint(
        "attendance_verdict_allowed",
        "conferences",
        "attendance_verdict IS NULL OR attendance_verdict IN "
        "('would_attend', 'unsure', 'would_not_attend')",
        schema="app",
    )
    # Backfill the edition from the date we already hold, so existing rows
    # are immediately usable as editions. Rows with no start_date keep a
    # null year rather than being given an invented one.
    op.execute(
        "UPDATE app.conferences "
        "SET edition_year = EXTRACT(YEAR FROM start_date)::smallint "
        "WHERE start_date IS NOT NULL"
    )

    # --- participation ----------------------------------------------------
    op.create_table(
        "participation",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conference_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable: the person may not be on the SME roster.
        sa.Column(
            "sme_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.smes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("person_label", sa.String(length=200), nullable=False),
        sa.Column("activity", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column(
            "talk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.talks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            _in_list("activity", _ACTIVITIES), name="activity_allowed"
        ),
        sa.CheckConstraint(
            f"outcome IS NULL OR {_in_list('outcome', _OUTCOMES)}",
            name="outcome_allowed",
        ),
        # Postgres treats NULLs as distinct here, so this constrains known
        # people only — two unmatched guest speakers must both be storable.
        sa.UniqueConstraint(
            "conference_id", "sme_id", "activity", name="uq_participation_person_activity"
        ),
        schema="app",
    )
    op.create_index(
        "ix_participation_conference_id", "participation", ["conference_id"], schema="app"
    )
    op.create_index("ix_participation_sme_id", "participation", ["sme_id"], schema="app")

    # --- the parallel table goes ------------------------------------------
    op.drop_table("past_conferences", schema="app")


def downgrade() -> None:
    # past_conferences is recreated empty. Its data was intentionally not
    # migrated forward, so there is nothing to migrate back.
    op.create_table(
        "past_conferences",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column(
            "series_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.conference_series.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "attended_sme_ids", sa.ARRAY(UUID(as_uuid=True)), nullable=False
        ),
        sa.Column(
            "attended_by_names_raw",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("session_type", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("imported_from", sa.String(length=120), nullable=True),
        sa.Column(
            "verdict",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unsure'"),
        ),
        sa.Column(
            "event_kind",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'corporate'"),
        ),
        sa.Column("conference_url", sa.String(length=500), nullable=True),
        sa.Column("location_city", sa.String(length=100), nullable=True),
        sa.Column("location_country", sa.String(length=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "event_kind IN ('corporate', 'grassroot', 'developer_day', "
            "'research', 'hackathon')",
            name="event_kind_allowed",
        ),
        schema="app",
    )

    op.drop_index("ix_participation_sme_id", table_name="participation", schema="app")
    op.drop_index(
        "ix_participation_conference_id", table_name="participation", schema="app"
    )
    op.drop_table("participation", schema="app")

    # Bare name plus type_: with type_ set, drop_constraint applies the
    # metadata naming convention itself and resolves this to
    # "ck_conferences_attendance_verdict_allowed". Passing the full name
    # here would have the convention applied a second time.
    op.drop_constraint(
        "attendance_verdict_allowed", "conferences", type_="check", schema="app"
    )
    for col in (
        "attendance_notes",
        "attendance_verdict",
        "audience_size_estimate",
        "spend_usd",
        "edition_year",
    ):
        op.drop_column("conferences", col, schema="app")
