"""Add app.conferences.cfp_url

Where to submit / view the full CFP. Separate from website (homepage)
so the dashboard + brief can link straight to the "Apply here" page.

Revision ID: 20260523_0000_cfp_url
Revises: 20260522_2300_settings
Create Date: 2026-05-23 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260523_0000_cfp_url"
down_revision: str | None = "20260522_2300_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conferences",
        sa.Column("cfp_url", sa.Text(), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("conferences", "cfp_url", schema="app")
