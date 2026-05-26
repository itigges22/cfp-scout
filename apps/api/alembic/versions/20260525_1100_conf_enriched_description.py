"""Add app.conferences.enriched_description

Stores a 2-3 sentence LLM-generated factual description of what the
conference is about — populated from the event name + topics + location.
The matcher's embedder uses this instead of the raw 14-word name+topics
blob so it has real semantic content to compare against messaging docs.

Without this, conferences whose feed entry is just a name + 5 topic tags
score near zero on messaging fit no matter how relevant they actually
are (vLLM Meetup, PyTorch Conference, Kubeflow GenAI Day all observed
at 0% pre-enrichment despite being slam-dunk matches).

Revision ID: 20260525_1100_enrich_desc
Revises: 20260523_0200_raw_att
Create Date: 2026-05-25 11:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260525_1100_enrich_desc"
down_revision: str | None = "20260523_0200_raw_att"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conferences",
        sa.Column("enriched_description", sa.Text(), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("conferences", "enriched_description", schema="app")
