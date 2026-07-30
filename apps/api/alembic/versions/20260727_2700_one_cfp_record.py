"""One record of a CfP submission, not two.

THE AMBIGUITY
    Two tables stored "this talk was pitched to this conference and here
    is what happened":

      talk_submissions            (talk_id, conference_id, submitted_by_sme_id,
                                   submitted_at, outcome)
      participation               (conference_id, sme_id, activity='talk',
                                   talk_id, outcome)

    Nothing reconciled them, and their vocabularies disagreed —
    talk_submissions allowed submitted/accepted/rejected/withdrawn,
    participation additionally allowed 'delivered'. The derived signals
    the talks library depends on (times_applied, is_flagged, reuse_check)
    counted only talk_submissions, so a submission recorded through
    participation was invisible to the reuse-risk warning.

    "Track CfP's that we have applied with to X conference" is one of the
    operator's stated core needs. Two systems of record means neither can
    be trusted.

WHY NOT MERGE THE TABLES
    Their uniqueness grains are incompatible. participation is UNIQUE on
    (conference_id, sme_id, activity) — one person, one activity, per
    conference. talk_submissions is UNIQUE on (talk_id, conference_id).
    If one person pitches TWO abstracts to one conference, that is two
    valid submissions and only one permitted participation row, so a
    naive merge silently drops one. Widening participation's constraint
    to include talk_id does not help: talk_id is NULL for booth/attend/
    sponsor and Postgres treats NULLs as distinct, so "Alice worked the
    booth" could then be inserted twice with no error.

THE ACTUAL FIX — they were never the same fact
    talk_submissions  we PITCHED this abstract to this conference, and
                      here is what came back.          (before the event)
    participation     this person SPOKE at this event. (at the event)

    Only ``participation.outcome`` conflated them. Its submission-shaped
    values (submitted / accepted / rejected / withdrawn) describe a
    pitch, not attendance; and 'delivered' — the one genuinely
    attendance-shaped value — is now expressed by ``attended_at`` and the
    derived ``has_attended`` from migration 20260727_1800.

    So the column goes, ``talk_id`` stays (which talk they gave is a real
    attendance fact), and there is exactly one place to record a
    submission.

SAFETY
    Nothing in the application READS participation.outcome for any
    decision — it is written and validated and then ignored. No UI writes
    it either; only talk_submissions has a submissions panel.

    Even so, this migration REFUSES TO RUN if any row has a non-null
    outcome, rather than dropping data it cannot see. A deployment where
    someone populated it by API stops here and a human looks, which is
    the correct outcome — silently discarding the operator's records is
    the failure this whole restructure has been removing.

Revision ID: 20260727_2700
Revises: 20260727_2600
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_2700"
down_revision = "20260727_2600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    populated = conn.execute(
        sa.text("SELECT count(*) FROM app.participation WHERE outcome IS NOT NULL")
    ).scalar()
    if populated:
        raise RuntimeError(
            f"{populated} participation row(s) have a non-null outcome. This "
            "migration drops that column because talk_submissions is the "
            "single record of a CfP submission, but it will not discard data "
            "it cannot see. Move those outcomes into app.talk_submissions "
            "first, then re-run."
        )

    op.drop_constraint("outcome_allowed", "participation", type_="check", schema="app")
    op.drop_column("participation", "outcome", schema="app")


def downgrade() -> None:
    op.add_column(
        "participation",
        sa.Column("outcome", sa.String(length=20), nullable=True),
        schema="app",
    )
    op.create_check_constraint(
        "outcome_allowed",
        "participation",
        "outcome IS NULL OR outcome IN "
        "('submitted', 'accepted', 'rejected', 'delivered', 'withdrawn')",
        schema="app",
    )
