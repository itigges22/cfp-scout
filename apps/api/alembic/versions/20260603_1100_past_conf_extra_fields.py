"""past_conferences: add event_kind, conference_url, location_city, location_country

Revision ID: 20260603_1100
Revises: 20260603_1000_v2_phase2_cleanup
Create Date: 2026-06-03 11:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260603_1100"
down_revision = "20260603_1000_v2_phase2_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "past_conferences",
        sa.Column("event_kind", sa.String(20), nullable=False, server_default="corporate"),
        schema="app",
    )
    op.add_column(
        "past_conferences",
        sa.Column("conference_url", sa.String(500), nullable=True),
        schema="app",
    )
    op.add_column(
        "past_conferences",
        sa.Column("location_city", sa.String(100), nullable=True),
        schema="app",
    )
    op.add_column(
        "past_conferences",
        sa.Column("location_country", sa.String(2), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("past_conferences", "location_country", schema="app")
    op.drop_column("past_conferences", "location_city", schema="app")
    op.drop_column("past_conferences", "conference_url", schema="app")
    op.drop_column("past_conferences", "event_kind", schema="app")
