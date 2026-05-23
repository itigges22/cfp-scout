"""Add app.past_conferences.attended_by_names_raw

Captures the attendee NAMES from the source CSV/spreadsheet (e.g. the
AI BU Developer Marketing 2026 Events sheet's `AI BU On-Site Staff`
column) alongside the resolved UUID list in `attended_sme_ids`. Even
when a name doesn't match any active SME at import time, the raw
string is preserved here so the operator can:

  - See who actually attended even before those people exist as SMEs
  - Link a name to an SME later via the edit dialog
  - Query "who's been to X" without needing every attendee in SMEs

Both lists are kept in sync by the mapper: a name that resolves to an
SME goes into BOTH attended_sme_ids AND attended_by_names_raw; a name
that doesn't resolve goes only into attended_by_names_raw.

Revision ID: 20260523_0200_raw_att
Revises: 20260523_0100_latlng
Create Date: 2026-05-23 02:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260523_0200_raw_att"
down_revision: str | None = "20260523_0100_latlng"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "past_conferences",
        sa.Column(
            "attended_by_names_raw",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("past_conferences", "attended_by_names_raw", schema="app")
