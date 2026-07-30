"""Drop content_versions — an unbounded table nothing ever read.

A global SQLAlchemy ``before_flush`` listener wrote a full JSON-Patch
snapshot for every modified versioned entity, on every flush, forever. The
git-blame view it existed to feed was never built: no screen in the SPA, and
no query outside the one endpoint that returned rows to nobody.

So it was a write on every save and a table that only grew, in exchange for
nothing. Removed rather than left dormant, because a dormant writer is still
a writer.

``audit.audit_log`` is deliberately KEPT. The distinction is worth stating:
an audit row is one deliberate record of a deliberate action, cheap and
answerable with a query when something looks wrong. An automatic full-row
snapshot on every flush is a cost looking for a reader.

The data is not preserved. It was never read, so there is nothing to migrate
to and nobody to migrate it for.

Revision ID: 20260726_1400
Revises: 20260726_1100
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260726_1400"
down_revision = "20260726_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_content_versions_entity", table_name="content_versions", schema="audit"
    )
    op.drop_table("content_versions", schema="audit")


def downgrade() -> None:
    # Recreated empty. The rows were never read, so there is nothing to
    # restore into it.
    op.create_table(
        "content_versions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("diff", JSONB(), nullable=False),
        sa.Column(
            "actor_label",
            sa.String(length=120),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        schema="audit",
    )
    op.create_index(
        "ix_content_versions_entity",
        "content_versions",
        ["entity_type", "entity_id"],
        schema="audit",
    )
