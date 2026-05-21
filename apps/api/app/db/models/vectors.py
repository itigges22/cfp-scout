"""Vector storage (the ``vectors`` schema).

``document_chunks.embedding`` uses pgvector's ``Vector`` type, dimension 768
to match ``nomic-embed-text-v1-5`` (the only embedding model MaaS exposes).

The HNSW index isn't created from the ORM — the initial migration creates it
via raw SQL because Alembic doesn't expose vector-specific index params.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import TimestampedMixin, uuid_pk


class EmbeddingModel(TimestampedMixin, Base):
    """Registry of embedding models. Lets us roll over to a new model
    without losing the old vectors — chunks carry the model_id they were
    embedded under."""

    __tablename__ = "embedding_models"
    __table_args__ = {"schema": "vectors"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    dimension: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(TimestampedMixin, Base):
    """Chunked + embedded text produced by Docling's HybridChunker (plan 11).

    ``owner_type`` + ``owner_id`` is a polymorphic ref (no FK constraint at
    the DB level since the owner table varies). The application layer keeps
    these in sync.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_owner", "owner_type", "owner_id"),
        # HNSW index on `embedding` is created by the initial migration via
        # raw SQL (Alembic doesn't expose pgvector index params).
        {"schema": "vectors"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    owner_type: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    chunk_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vectors.embedding_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)

    # Docling structural info: {section_heading, page_number, content_type}.
    # `{}` for non-document inputs (manual messaging entries, SME bios).
    chunk_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # Bumped on retrieval; drives decay (plan 25).
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
