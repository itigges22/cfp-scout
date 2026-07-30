"""embedding model rollover: nomic-embed-text-v1-5 → Nomic-embed-text-v2-moe

The LiteMaaS backend decommissioned ``nomic-embed-text-v1-5`` and now
serves ``Nomic-embed-text-v2-moe`` (same 768 dimension, so
``document_chunks.embedding vector(768)`` needs no DDL change). This
registers the new model row and makes it the single active one; the old
row is kept (deprecated) so historical chunks stay attributed.

Vectors from the two models are NOT comparable — after this migration
runs, re-embed content so the matcher has chunks under the new model:

    python -m app.maintenance enrich-conferences --force   # conferences
    python -m app.maintenance enrich-pillars --force       # pillars
    python -m app.maintenance reembed-owners               # SMEs, audiences, messaging

The third command is NOT optional: SME bios, audience profiles and
messaging documents are embedded too, and until they are re-embedded
under the new model Stage A (messaging fit) and Stage C (SME match)
retrieve nothing and silently score 0. The previous instructions listed
only the first two.

Revision ID: 20260705_1000_embed_v2moe
Revises: 20260604_1100
Create Date: 2026-07-05 10:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260705_1000_embed_v2moe"
down_revision: str | None = "20260604_1100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO vectors.embedding_models (name, provider, dimension, is_active)
        VALUES ('Nomic-embed-text-v2-moe', 'llm-endpoint', 768, false)
        ON CONFLICT (name) DO NOTHING;
        """
    )
    op.execute(
        """
        UPDATE vectors.embedding_models
        SET is_active = false, deprecated_at = now()
        WHERE name <> 'Nomic-embed-text-v2-moe' AND is_active = true;
        """
    )
    op.execute(
        """
        UPDATE vectors.embedding_models
        SET is_active = true, deprecated_at = NULL
        WHERE name = 'Nomic-embed-text-v2-moe';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE vectors.embedding_models
        SET is_active = false, deprecated_at = now()
        WHERE name = 'Nomic-embed-text-v2-moe';
        """
    )
    op.execute(
        """
        UPDATE vectors.embedding_models
        SET is_active = true, deprecated_at = NULL
        WHERE name = 'nomic-embed-text-v1-5';
        """
    )
