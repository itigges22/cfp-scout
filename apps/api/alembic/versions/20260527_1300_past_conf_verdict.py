"""Add app.past_conferences.verdict

Operator feedback signal: was attending this conference actually
worth it? Three values:
  - ``would_attend``: yes, send someone again to a future edition
  - ``unsure``: default; no retrospective opinion yet
  - ``would_not_attend``: no, not worth our time

The matcher's ``series_memory`` boost reads this column live (no
LLM, no cache invalidation) when computing each conference's
overall_score. So flipping a verdict in the UI re-orders the
upcoming-conferences list on the next page load with zero LLM cost
and zero rescore delay.

Existing rows default to ``unsure`` — the operator can opt into
verdicts as they review past events.

Revision ID: 20260527_1300_pc_verdict
Revises: 20260526_2200_judge_cache
Create Date: 2026-05-27 13:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_1300_pc_verdict"
down_revision: str | None = "20260526_2200_judge_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Use a CHECK constraint rather than a Postgres ENUM so that
# evolving the value set later doesn't require a migration to add
# new enum members (Postgres enums are notoriously rigid).
_ALLOWED = ("would_attend", "unsure", "would_not_attend")


def upgrade() -> None:
    op.add_column(
        "past_conferences",
        sa.Column(
            "verdict",
            sa.String(length=20),
            nullable=False,
            server_default="unsure",
        ),
        schema="app",
    )
    op.create_check_constraint(
        "ck_past_conferences_verdict",
        "past_conferences",
        sa.column("verdict").in_(_ALLOWED),
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_past_conferences_verdict",
        "past_conferences",
        schema="app",
        type_="check",
    )
    op.drop_column("past_conferences", "verdict", schema="app")
