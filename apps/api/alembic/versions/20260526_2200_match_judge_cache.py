"""Add app.matches.judge_input_hash for judge response cache

The Stage D LLM-as-judge cross-encoder costs ~$0.0005 per call and
takes 2-3 seconds at the user-level MaaS rate limit. Full bulk
rescores (576 conferences) cost $0.30 and 22 minutes wall time.

Most of those calls are wasted: the conference's enriched
description rarely changes between rescores. Cache the judge result
keyed by a hash of (conference enriched_description + the full
pillar context + the prompt version). If the hash matches the
stored value, the matcher reuses the cached score + rationale
without calling the LLM.

Char(64) for a hex SHA-256 — small, fixed-width, fits in an index
if we ever want to dedupe more aggressively.

Revision ID: 20260526_2200_judge_cache
Revises: 20260526_1700_judge_score
Create Date: 2026-05-26 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260526_2200_judge_cache"
down_revision: str | None = "20260526_1700_judge_score"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("judge_input_hash", sa.CHAR(length=64), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("matches", "judge_input_hash", schema="app")
