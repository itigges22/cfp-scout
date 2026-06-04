"""SCOUT v2 Phase 1 — Additive schema migrations A through I.

Migrations A–I from docs/planning/01-schema.md. All additive; nothing
existing is removed or renamed.  Phase 2 cleanup (J + K) ships separately.

  A: event_kind + assigned_pillar_id on conferences
  B: pillar_id on audience_profiles
  C: sme_pillars junction
  D: talks table
  E: talk_tags + talk_tag_assignments
  F: talk_topics junction
  G: talk_submissions table
  H: pillar_content_roadmap table
  I: pillar_gtm_strategy table

Revision ID: 20260603_0900_v2_phase1
Revises: 20260527_1300_pc_verdict
Create Date: 2026-06-03 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_0900_v2_phase1"
down_revision: str | None = "20260527_1300_pc_verdict"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "app"


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Migration A: event_kind + assigned_pillar_id on conferences
    # -----------------------------------------------------------------------
    op.add_column(
        "conferences",
        sa.Column(
            "event_kind",
            sa.Text(),
            nullable=False,
            server_default="corporate",
        ),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "conferences_event_kind_check",
        "conferences",
        sa.column("event_kind").in_(
            ["corporate", "developer_day", "team_managed", "meetup", "research"]
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "conferences",
        sa.Column(
            "assigned_pillar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "app.strategic_pillars.id",
                ondelete="SET NULL",
                name="fk_conferences_assigned_pillar_id",
            ),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_conferences_event_kind",
        "conferences",
        ["event_kind"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_conferences_assigned_pillar_id",
        "conferences",
        ["assigned_pillar_id"],
        schema=_SCHEMA,
    )

    # -----------------------------------------------------------------------
    # Migration B: pillar_id on audience_profiles
    # -----------------------------------------------------------------------
    op.add_column(
        "audience_profiles",
        sa.Column(
            "pillar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "app.strategic_pillars.id",
                ondelete="SET NULL",
                name="fk_audience_profiles_pillar_id",
            ),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audience_profiles_pillar_id",
        "audience_profiles",
        ["pillar_id"],
        schema=_SCHEMA,
    )

    # -----------------------------------------------------------------------
    # Migration C: sme_pillars junction
    # -----------------------------------------------------------------------
    op.create_table(
        "sme_pillars",
        sa.Column("sme_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pillar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(
            ["sme_id"],
            ["app.smes.id"],
            ondelete="CASCADE",
            name="fk_sme_pillars_sme_id",
        ),
        sa.ForeignKeyConstraint(
            ["pillar_id"],
            ["app.strategic_pillars.id"],
            ondelete="CASCADE",
            name="fk_sme_pillars_pillar_id",
        ),
        sa.PrimaryKeyConstraint("sme_id", "pillar_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_sme_pillars_pillar_id",
        "sme_pillars",
        ["pillar_id"],
        schema=_SCHEMA,
    )

    # -----------------------------------------------------------------------
    # Migration D: talks table
    # -----------------------------------------------------------------------
    op.create_table(
        "talks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("full_content", sa.Text(), nullable=True),
        sa.Column(
            "source_type",
            sa.Text(),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("pillar_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("primary_sme_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "co_speaker_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column("talk_format", sa.Text(), nullable=True),
        sa.Column("suggested_duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "source_type IN ('uploaded', 'manual')",
            name="talks_source_type_check",
        ),
        sa.CheckConstraint(
            "talk_format IN ('keynote', 'talk', 'panel', 'workshop', 'tutorial', 'other') OR talk_format IS NULL",
            name="talks_format_check",
        ),
        sa.CheckConstraint(
            "review_status IN ('draft', 'pending_review', 'approved')",
            name="talks_review_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["pillar_id"],
            ["app.strategic_pillars.id"],
            ondelete="SET NULL",
            name="fk_talks_pillar_id",
        ),
        sa.ForeignKeyConstraint(
            ["primary_sme_id"],
            ["app.smes.id"],
            ondelete="SET NULL",
            name="fk_talks_primary_sme_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index("ix_talks_pillar_id", "talks", ["pillar_id"], schema=_SCHEMA)
    op.create_index("ix_talks_primary_sme_id", "talks", ["primary_sme_id"], schema=_SCHEMA)
    op.create_index("ix_talks_review_status", "talks", ["review_status"], schema=_SCHEMA)
    op.create_index("ix_talks_is_active", "talks", ["is_active"], schema=_SCHEMA)

    # -----------------------------------------------------------------------
    # Migration E: talk_tags + talk_tag_assignments
    # -----------------------------------------------------------------------
    op.create_table(
        "talk_tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_talk_tags_name"),
        schema=_SCHEMA,
    )

    op.create_table(
        "talk_tag_assignments",
        sa.Column("talk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["talk_id"],
            ["app.talks.id"],
            ondelete="CASCADE",
            name="fk_talk_tag_assignments_talk_id",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["app.talk_tags.id"],
            ondelete="CASCADE",
            name="fk_talk_tag_assignments_tag_id",
        ),
        sa.PrimaryKeyConstraint("talk_id", "tag_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_talk_tag_assignments_tag_id",
        "talk_tag_assignments",
        ["tag_id"],
        schema=_SCHEMA,
    )

    # -----------------------------------------------------------------------
    # Migration F: talk_topics junction
    # -----------------------------------------------------------------------
    op.create_table(
        "talk_topics",
        sa.Column("talk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "weight",
            sa.Numeric(),
            nullable=False,
            server_default="1.0",
        ),
        sa.ForeignKeyConstraint(
            ["talk_id"],
            ["app.talks.id"],
            ondelete="CASCADE",
            name="fk_talk_topics_talk_id",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["app.topics.id"],
            ondelete="CASCADE",
            name="fk_talk_topics_topic_id",
        ),
        sa.PrimaryKeyConstraint("talk_id", "topic_id"),
        schema=_SCHEMA,
    )
    op.create_index("ix_talk_topics_topic_id", "talk_topics", ["topic_id"], schema=_SCHEMA)

    # -----------------------------------------------------------------------
    # Migration G: talk_submissions
    # -----------------------------------------------------------------------
    op.create_table(
        "talk_submissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("talk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submitted_by_sme_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.Date(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "outcome IN ('submitted', 'accepted', 'rejected', 'withdrawn') OR outcome IS NULL",
            name="talk_submissions_outcome_check",
        ),
        sa.ForeignKeyConstraint(
            ["talk_id"],
            ["app.talks.id"],
            ondelete="CASCADE",
            name="fk_talk_submissions_talk_id",
        ),
        sa.ForeignKeyConstraint(
            ["conference_id"],
            ["app.conferences.id"],
            ondelete="CASCADE",
            name="fk_talk_submissions_conference_id",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_sme_id"],
            ["app.smes.id"],
            ondelete="SET NULL",
            name="fk_talk_submissions_sme_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "talk_id",
            "conference_id",
            name="uq_talk_submissions_talk_conference",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_talk_submissions_talk_id", "talk_submissions", ["talk_id"], schema=_SCHEMA
    )
    op.create_index(
        "ix_talk_submissions_conference_id",
        "talk_submissions",
        ["conference_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_talk_submissions_sme_id",
        "talk_submissions",
        ["submitted_by_sme_id"],
        schema=_SCHEMA,
    )

    # -----------------------------------------------------------------------
    # Migration H: pillar_content_roadmap
    # -----------------------------------------------------------------------
    op.create_table(
        "pillar_content_roadmap",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("pillar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quarter", sa.Text(), nullable=False),
        sa.Column(
            "goals",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("owner_label", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["pillar_id"],
            ["app.strategic_pillars.id"],
            ondelete="CASCADE",
            name="fk_pillar_content_roadmap_pillar_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_pillar_content_roadmap_pillar_id",
        "pillar_content_roadmap",
        ["pillar_id"],
        schema=_SCHEMA,
    )

    # -----------------------------------------------------------------------
    # Migration I: pillar_gtm_strategy
    # -----------------------------------------------------------------------
    op.create_table(
        "pillar_gtm_strategy",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("pillar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column(
            "key_messages",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "target_audience_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["pillar_id"],
            ["app.strategic_pillars.id"],
            ondelete="CASCADE",
            name="fk_pillar_gtm_strategy_pillar_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_pillar_gtm_strategy_pillar_id",
        "pillar_gtm_strategy",
        ["pillar_id"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    # Reverse order of upgrade
    op.drop_table("pillar_gtm_strategy", schema=_SCHEMA)
    op.drop_table("pillar_content_roadmap", schema=_SCHEMA)
    op.drop_table("talk_submissions", schema=_SCHEMA)
    op.drop_table("talk_topics", schema=_SCHEMA)
    op.drop_table("talk_tag_assignments", schema=_SCHEMA)
    op.drop_table("talk_tags", schema=_SCHEMA)
    op.drop_table("talks", schema=_SCHEMA)
    op.drop_table("sme_pillars", schema=_SCHEMA)

    op.drop_index("ix_audience_profiles_pillar_id", "audience_profiles", schema=_SCHEMA)
    op.drop_column("audience_profiles", "pillar_id", schema=_SCHEMA)

    op.drop_index("ix_conferences_assigned_pillar_id", "conferences", schema=_SCHEMA)
    op.drop_index("ix_conferences_event_kind", "conferences", schema=_SCHEMA)
    op.drop_column("conferences", "assigned_pillar_id", schema=_SCHEMA)
    op.drop_constraint("conferences_event_kind_check", "conferences", schema=_SCHEMA, type_="check")
    op.drop_column("conferences", "event_kind", schema=_SCHEMA)
