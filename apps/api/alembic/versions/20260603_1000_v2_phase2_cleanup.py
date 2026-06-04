"""SCOUT v2 Phase 2 — Cleanup migrations J and K.

  J: Drop expertise_areas column from app.smes
     (sme_topics junction is now the authoritative source for SME expertise)
  K: Seed SME_MAX_TOPICS=5 into app_setting_overrides

Revision ID: 20260603_1000_v2_phase2_cleanup
Revises: 20260603_0900_v2_phase1
Create Date: 2026-06-03 10:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_1000_v2_phase2_cleanup"
down_revision: str | None = "20260603_0900_v2_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "app"


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Migration J: Drop expertise_areas from smes
    # -----------------------------------------------------------------------
    op.drop_column("smes", "expertise_areas", schema=_SCHEMA)

    # -----------------------------------------------------------------------
    # Migration K: Seed SME_MAX_TOPICS setting
    # -----------------------------------------------------------------------
    op.execute(
        sa.text(
            "INSERT INTO app.app_setting_overrides (name, value, actor_label) "
            "VALUES ('SME_MAX_TOPICS', '5', 'system-seed') "
            "ON CONFLICT (name) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM app.app_setting_overrides WHERE name = 'SME_MAX_TOPICS'"
        )
    )
    op.add_column(
        "smes",
        sa.Column(
            "expertise_areas",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        schema=_SCHEMA,
    )
