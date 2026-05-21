"""seed embedding model

Inserts the one embedding model row Scout needs to function at all:
``nomic-embed-text-v1-5``, dim 768, active. Without this row, plan 11's
embedder has nothing to attribute chunks to.

Other seed data (strategic_pillars, conference_series, topics, audiences)
is entered by the team via the XLSX workbook (plan 31) — we don't ship
defaults for those.

Revision ID: 20260521_1210_seed_embedding_model
Revises: 20260521_1200_baseline
Create Date: 2026-05-21 12:10:00
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_1210_seed_embedding_model"
down_revision: str | None = "20260521_1200_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO vectors.embedding_models (name, provider, dimension, is_active)
        VALUES ('nomic-embed-text-v1-5', 'maas', 768, true)
        ON CONFLICT (name) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM vectors.embedding_models WHERE name = 'nomic-embed-text-v1-5';"
    )
