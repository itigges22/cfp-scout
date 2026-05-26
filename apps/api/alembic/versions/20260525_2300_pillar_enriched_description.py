"""Add app.strategic_pillars.enriched_description

Stores a long-form (500-800 word) pillar description extracted from
the operator's messaging documents via the LLM. The matcher's stage B
uses this in place of the short ``description`` field when present.

Without this, all 4 pillars share too much vocabulary at their short-
description level — almost every AI conference clears the rescale
ceiling against at least one pillar, so stage B saturates at 100%
for the entire conference set and contributes no ranking signal.

Revision ID: 20260525_2300_pillar_enrich
Revises: 20260525_1100_enrich_desc
Create Date: 2026-05-25 23:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260525_2300_pillar_enrich"
down_revision: str | None = "20260525_1100_enrich_desc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strategic_pillars",
        sa.Column("enriched_description", sa.Text(), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("strategic_pillars", "enriched_description", schema="app")
