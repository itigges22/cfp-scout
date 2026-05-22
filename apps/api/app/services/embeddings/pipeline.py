"""Embedding pipeline: text → chunks → vectors → ``vectors.document_chunks``.

The single public entry point ``embed_owner()`` is idempotent and safe to
re-run: it deletes the prior chunk rows for the (owner_type, owner_id,
active_embedding_model) tuple before inserting new ones.

Callers don't catch exceptions; the route layer translates them into
problem+json. The matcher (plan 17) treats a failed embed as "this entity
is unreachable for similarity search" and surfaces it on /diagnostics.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vectors import DocumentChunk, EmbeddingModel
from app.services.embeddings.chunker import ChunkData, chunk_text
from app.services.llm import EmbeddingRequest, LLMClient, get_llm_client

log = structlog.get_logger("scout.embeddings")


# Owner types defined by the schema (`document_chunks.owner_type` enum).
# Validated here so callers can't introduce typos that break filtering.
VALID_OWNER_TYPES = {"messaging", "audience", "conference", "sme_bio", "raw_page"}


async def get_active_embedding_model(db: AsyncSession) -> EmbeddingModel:
    """Return the row in ``vectors.embedding_models`` with ``is_active=true``.

    Raises ``RuntimeError`` if zero or more-than-one are active.
    """
    result = await db.execute(select(EmbeddingModel).where(EmbeddingModel.is_active.is_(True)))
    rows = list(result.scalars().all())
    if not rows:
        raise RuntimeError(
            "no active embedding model — vectors.embedding_models has no is_active=true row. "
            "Did the plan-06 seed migration run? (`make migrate`)"
        )
    if len(rows) > 1:
        raise RuntimeError(
            f"multiple active embedding models ({len(rows)}); deactivate all but one before embedding."
        )
    return rows[0]


async def embed_owner(
    db: AsyncSession,
    *,
    owner_type: str,
    owner_id: UUID,
    text: str,
    purpose: str | None = None,
    extra_metadata: dict | None = None,
    client: LLMClient | None = None,
) -> int:
    """Chunk + embed + persist. Idempotent: re-running replaces prior chunks
    for the same (owner_type, owner_id) under the active model.

    Empty/whitespace input is a no-op: existing chunks are still deleted
    (so deactivating an entity removes its retrieval surface) but no new
    rows are inserted.

    Args:
        db: open AsyncSession. Caller commits.
        owner_type: one of VALID_OWNER_TYPES.
        owner_id: the UUID of the source entity.
        text: full text to embed.
        purpose: tag passed to the LLM client for cost accounting.
                  Defaults to ``f"embed:{owner_type}"``.
        extra_metadata: merged into each chunk's ``chunk_metadata``. Plan 12
                        will pass page numbers / section headings here.
        client: override the LLM client (for tests).

    Returns:
        The number of chunks inserted (0 for empty/whitespace input).
    """
    if owner_type not in VALID_OWNER_TYPES:
        raise ValueError(f"invalid owner_type {owner_type!r}; valid: {sorted(VALID_OWNER_TYPES)}")

    model_row = await get_active_embedding_model(db)

    # Delete prior chunks for this owner under the active model. Other-model
    # chunks (during rollovers) stay until the reindex job (plan 13) catches them.
    await db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.owner_type == owner_type,
            DocumentChunk.owner_id == owner_id,
            DocumentChunk.embedding_model_id == model_row.id,
        )
    )

    chunks: list[ChunkData] = chunk_text(text)
    if not chunks:
        log.info(
            "embed.no_chunks",
            owner_type=owner_type,
            owner_id=str(owner_id),
            reason="empty_or_whitespace_input",
        )
        return 0

    client = client or get_llm_client()
    response = await client.embed(
        EmbeddingRequest(
            texts=[c.text for c in chunks],
            purpose=purpose or f"embed:{owner_type}",
        ),
        db=db,
    )

    if len(response.vectors) != len(chunks):
        raise RuntimeError(
            f"embedder returned {len(response.vectors)} vectors but we sent "
            f"{len(chunks)} chunks (owner_type={owner_type}, owner_id={owner_id})."
        )

    extra = extra_metadata or {}
    for chunk, vec in zip(chunks, response.vectors, strict=True):
        merged_metadata = {**chunk.metadata, **extra}
        db.add(
            DocumentChunk(
                owner_type=owner_type,
                owner_id=owner_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                embedding_model_id=model_row.id,
                embedding=vec,
                chunk_metadata=merged_metadata,
            )
        )

    log.info(
        "embed.complete",
        owner_type=owner_type,
        owner_id=str(owner_id),
        chunks=len(chunks),
        model=model_row.name,
        embedder_tokens=response.prompt_tokens,
        embedder_cost_usd=response.cost_usd,
    )
    # Caller commits.
    return len(chunks)
