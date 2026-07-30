"""Drop messaging_pillars — a second representation nothing ever wrote.

``matcher/pillars.py`` joined this junction to collect the messaging
evidence backing each strategic pillar. Nothing in the application ever
inserted a row into it: ``MessagingPillar`` had zero constructor calls
anywhere under ``app/``. So the query returned nothing on every run, and
each pillar was represented to the scorer by its own description
embedding alone — without the messaging evidence the stage was designed
around.

The link the application does maintain is the scalar
``messaging_documents.pillar_id``. It is part of ``MessagingDocumentBase``,
so every create and update carries it, and the messaging API exposes it.
Two representations of one fact, and the matcher was reading the dead one.

``pillars.py`` now joins on that column. This migration removes the
junction so a third reader cannot pick the wrong one later.

No data is lost: the table is empty by construction. The downgrade
recreates the structure but cannot repopulate it, which is accurate —
there was never anything in it to restore.

One capability does narrow. The junction carried a ``weight`` and allowed
a document to back several pillars; the scalar column allows exactly one
pillar per document, unweighted. Neither was ever exercised — no writer
existed to exercise them — and a many-to-many can be reintroduced if the
need turns out to be real rather than anticipated.

Revision ID: 20260727_1100
Revises: 20260727_0900
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260727_1100"
down_revision = "20260727_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("messaging_pillars", schema="app")


def downgrade() -> None:
    op.create_table(
        "messaging_pillars",
        sa.Column(
            "messaging_document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.messaging_documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "pillar_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        schema="app",
    )
