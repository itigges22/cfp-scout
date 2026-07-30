"""Add doc_kind to messaging_documents.

Revision ID: 20260604_0900_messaging_doc_kind
Revises: 20260603_1100_past_conf_extra_fields
Create Date: 2026-06-04 09:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_0900"
down_revision = "20260603_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messaging_documents",
        sa.Column(
            "doc_kind",
            sa.String(30),
            nullable=False,
            server_default="other",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("messaging_documents", "doc_kind", schema="app")
