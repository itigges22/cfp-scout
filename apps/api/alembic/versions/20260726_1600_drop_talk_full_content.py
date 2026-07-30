"""Drop talks.full_content — accepted, stored, read by nothing.

The column was settable through POST/PATCH /talks and typed end to end into
the web client, so it looked like a feature. Nothing ever read it: not the
embedder (which embeds title + abstract), not talk_service, not the matcher,
and no component rendered it.

Storing the full text of every talk to never look at it is the expensive
version of the write-only problem — unlike a small JSONB column, this is
unbounded prose.

Revision ID: 20260726_1600
Revises: 20260726_1400
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_1600"
down_revision = "20260726_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("talks", "full_content", schema="app")


def downgrade() -> None:
    # Recreated empty; the contents were never read, so there is nothing to
    # restore into it.
    op.add_column(
        "talks", sa.Column("full_content", sa.Text(), nullable=True), schema="app"
    )
