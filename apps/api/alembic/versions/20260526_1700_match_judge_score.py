"""Add app.matches.judge_score and judge_rationale

Stage D of the matcher: an LLM-as-judge "reranker" that scores each
conference against the full messaging + pillar context in one prompt,
returning a single 0..1 score plus a short rationale. This catches
relevance the dense embedder + lexical signal miss because the
embedder works on whole-document averages and the lexical scorer
only sees surface tokens — neither can reason about whether a
conference's specific focus actually aligns with the operator's
strategy.

See ADR-0008 for the design rationale and links to the cross-encoder
reranker literature this stage implements (in spirit — we use the
chat LLM as the cross-encoder since no dedicated reranker model is
available on the operator's MaaS key).

Revision ID: 20260526_1700_judge_score
Revises: 20260525_2300_pillar_enrich
Create Date: 2026-05-26 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260526_1700_judge_score"
down_revision: str | None = "20260525_2300_pillar_enrich"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("judge_score", sa.Float(), nullable=True),
        schema="app",
    )
    op.add_column(
        "matches",
        sa.Column(
            "judge_rationale",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("matches", "judge_rationale", schema="app")
    op.drop_column("matches", "judge_score", schema="app")
