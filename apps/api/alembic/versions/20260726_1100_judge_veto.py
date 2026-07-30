"""The judge returns a verdict, not a score.

``judge_score`` was a 0-100 relevance number that got folded into the
weighted mean. It is replaced by ``judge_verdict`` ('ok' | 'veto') because
that is the only decision the judge was ever making well, and because a veto
averaged into a mean produces a number nobody can explain.

``judge_rationale`` becomes ``judge_reason`` — it is now shown to a human in
a review queue rather than kept for audit, so the name should say so.

Existing judge scores are not translated into verdicts. A score below some
threshold is not the same statement as "the wrong people are in this room",
and inventing vetoes from old numbers would put conferences in the review
queue with reasons nobody wrote. Rows keep a NULL verdict until the next
matcher run, which is the honest representation of "not yet judged".

Revision ID: 20260726_1100
Revises: 20260726_0900
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_1100"
down_revision = "20260726_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("judge_verdict", sa.String(length=10), nullable=True),
        schema="app",
    )
    op.create_check_constraint(
        "judge_verdict_allowed",
        "matches",
        "judge_verdict IS NULL OR judge_verdict IN ('ok', 'veto')",
        schema="app",
    )
    op.alter_column(
        "matches",
        "judge_rationale",
        new_column_name="judge_reason",
        schema="app",
    )
    op.drop_column("matches", "judge_score", schema="app")

    # Every cached verdict is from the old prompt, which was a lookup table
    # of named venues. Clearing the hash forces a fresh judgement rather
    # than serving an opinion the new prompt would not have reached.
    op.execute("UPDATE app.matches SET judge_input_hash = NULL")


def downgrade() -> None:
    op.add_column(
        "matches", sa.Column("judge_score", sa.Float(), nullable=True), schema="app"
    )
    op.alter_column(
        "matches",
        "judge_reason",
        new_column_name="judge_rationale",
        schema="app",
    )
    op.drop_constraint(
        "judge_verdict_allowed", "matches", type_="check", schema="app"
    )
    op.drop_column("matches", "judge_verdict", schema="app")
