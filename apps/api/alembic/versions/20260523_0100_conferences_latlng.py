"""Add app.conferences.latitude / longitude

Best-effort geocoded coordinates for the dashboard map. NULL until the
geocoding pass has run. Plain floats — no PostGIS dependency. City-level
resolution is sufficient for the "where are AI events happening" view.

Revision ID: 20260523_0100_latlng
Revises: 20260523_0000_cfp_url
Create Date: 2026-05-23 01:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260523_0100_latlng"
down_revision: str | None = "20260523_0000_cfp_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conferences",
        sa.Column("latitude", sa.Float(), nullable=True),
        schema="app",
    )
    op.add_column(
        "conferences",
        sa.Column("longitude", sa.Float(), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("conferences", "longitude", schema="app")
    op.drop_column("conferences", "latitude", schema="app")
