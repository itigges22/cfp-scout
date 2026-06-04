"""Pillar-scoped messaging docs: add pillar_id; drop old GTM + roadmap tables.

Revision ID: 20260604_1000
Revises: 20260604_0900
Create Date: 2026-06-04 10:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260604_1000"
down_revision = "20260604_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add pillar_id to messaging_documents (nullable — existing docs are un-scoped)
    op.add_column(
        "messaging_documents",
        sa.Column("pillar_id", UUID(as_uuid=True), sa.ForeignKey("app.strategic_pillars.id", ondelete="SET NULL"), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_messaging_documents_pillar_id",
        "messaging_documents",
        ["pillar_id"],
        schema="app",
    )

    # Drop old per-pillar GTM + roadmap tables (replaced by messaging_documents)
    op.drop_table("pillar_gtm_strategy", schema="app")
    op.drop_table("pillar_content_roadmap", schema="app")


def downgrade() -> None:
    op.drop_index("ix_messaging_documents_pillar_id", table_name="messaging_documents", schema="app")
    op.drop_column("messaging_documents", "pillar_id", schema="app")
    # Recreating the dropped tables on downgrade is intentionally omitted.
