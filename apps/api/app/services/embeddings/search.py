"""Vector similarity search.

Given a query string, embed it and return the top-k most-similar chunks
across (optionally filtered) owner types. Used by the matcher (plan 17),
the agent chat retrieval step (plan 22), and the topics-of-interest matcher.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.vectors import DocumentChunk
from app.services.embeddings.pipeline import get_active_embedding_model
from app.services.llm import EmbeddingRequest, LLMClient, get_llm_client

log = structlog.get_logger("scout.embeddings.search")


async def similar_chunks(
    db: AsyncSession,
    *,
    query: str,
    owner_types: Sequence[str] | None = None,
    owner_ids: Sequence[UUID] | None = None,
    k: int = 10,
    purpose: str = "similarity_search",
    bump_last_used: bool = True,
    client: LLMClient | None = None,
) -> list[DocumentChunk]:
    """Embed `query`, return the k chunks closest to it by cosine distance.

    Optionally filter by `owner_types` (e.g. ``["messaging"]`` for Stage A
    of the matcher) and/or `owner_ids` (for "search within these specific
    SMEs only").

    Args:
        db: open AsyncSession. Caller commits if relevant (we record
            ``last_used_at`` on hits when ``bump_last_used=True``).
        query: free-text question.
        owner_types: restrict to these chunk owner types. None = all.
        owner_ids: restrict to chunks whose owner_id is in this set. None = all.
        k: number of chunks to return.
        purpose: cost-accounting tag for the embedding call.
        bump_last_used: update last_used_at on returned chunks. Drives Ebbinghaus
            decay (plan 25). Pass False from background jobs / admin views.
        client: override the LLM client (for tests).

    Returns:
        Up to k DocumentChunk rows, ordered closest-first.
    """
    if k <= 0:
        return []
    if not query or not query.strip():
        return []

    model_row = await get_active_embedding_model(db)
    client = client or get_llm_client()
    response = await client.embed(
        EmbeddingRequest(texts=[query], purpose=purpose),
        db=db,
    )
    query_vec = response.vectors[0]

    # pgvector exposes .cosine_distance(other) on Vector columns. Lower is closer.
    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.embedding_model_id == model_row.id)
        .order_by(DocumentChunk.embedding.cosine_distance(query_vec))
        .limit(k)
    )
    if owner_types:
        stmt = stmt.where(DocumentChunk.owner_type.in_(list(owner_types)))
    if owner_ids:
        stmt = stmt.where(DocumentChunk.owner_id.in_(list(owner_ids)))

    result = await db.execute(stmt)
    hits = list(result.scalars().all())

    # Bump last_used_at on the hits so plan 25's decay keeps fresh chunks
    # prominent. Skipped for admin/diagnostic searches to avoid polluting decay.
    if hits and bump_last_used:
        await db.execute(
            update(DocumentChunk)
            .where(DocumentChunk.id.in_([h.id for h in hits]))
            .values(last_used_at=datetime.now(tz=UTC))
        )

    log.debug(
        "embedding.search.complete",
        query_chars=len(query),
        hits=len(hits),
        owner_types=list(owner_types) if owner_types else None,
        k=k,
    )
    return hits
