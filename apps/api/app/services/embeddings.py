"""Text in, vectors out: chunking, embedding, and similarity search.

WHAT THIS DOES
    Splits a document into overlapping chunks, embeds them through the
    provider, stores them with their source reference, and searches them by
    cosine distance.

HOW IT CONNECTS
    Called by   services/pdf.py, services/matcher, services/agent.py, and
                the admin embeddings routes
    Writes      the embedding chunk tables
    Helpers     services/llm for the embedding call

WORTH KNOWING
    Chunking, embedding and searching are one round trip in three steps
    and were three files; ``search`` had no consumer outside the package
    at all. A change to chunk size is meaningless without seeing what
    searches those chunks.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NamedTuple
from uuid import UUID

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk, EmbeddingModel
from app.services.llm import EmbeddingRequest, LLMClient, get_llm_client
from app.settings import get_settings

log = structlog.get_logger("scout.embeddings")


# ==========================================================================
# chunker.py
# ==========================================================================


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z\(\"])")


_CHARS_PER_TOKEN = 4






@dataclass(slots=True)
class ChunkData:
    """One chunk produced by the chunker.

    `metadata` is a free-form dict the PDF path fills with Docling info
    (section_heading, page_number, content_type). For plain-text inputs it
    stays empty.
    """

    text: str
    chunk_index: int
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_text(
    text: str,
    *,
    max_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[ChunkData]:
    """Split `text` into overlapping, sentence-aware chunks.

    Behaviour:
      * Strips leading/trailing whitespace; collapses runs of whitespace to single spaces.
      * Returns [] for empty / whitespace-only input.
      * Greedy: stuffs sentences into chunks up to ``max_chars`` then breaks.
        When a single sentence exceeds ``max_chars``, hard-splits at char boundaries.
      * Adjacent chunks overlap by approximately ``overlap_chars`` (clipped to
        sentence boundary inside the overlap region where possible).
    """
    # None means "use the operator setting"; resolved here rather than in
    # the signature because a default argument is evaluated once at import
    # and would freeze the value before any override is loaded.
    _s = get_settings()
    max_chars = _s.embedding_chunk_max_chars if max_chars is None else max_chars
    overlap_chars = (
        _s.embedding_chunk_overlap_chars if overlap_chars is None else overlap_chars
    )

    cleaned = _normalize(text)
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [_make_chunk(cleaned, 0)]

    sentences = _split_sentences(cleaned)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        if len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            # Start new chunk with overlap from the tail of the previous one.
            overlap = _tail_overlap(current, overlap_chars)
            current = f"{overlap} {sentence}".strip() if overlap else sentence
    if current:
        chunks.append(current)

    # Some "sentences" may individually exceed max_chars (a giant URL block,
    # base64 dump in scraped HTML, etc.). Hard-split those.
    expanded: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            expanded.append(c)
        else:
            expanded.extend(_hard_split(c, max_chars, overlap_chars))

    return [_make_chunk(t, i) for i, t in enumerate(expanded)]


def _normalize(text: str) -> str:
    """Strip + collapse whitespace runs to single spaces. Idempotent."""
    return re.sub(r"\s+", " ", text or "").strip()


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_BOUNDARY.split(text) if s]


def _tail_overlap(chunk: str, overlap_chars: int) -> str:
    """Return the last ~overlap_chars of `chunk`, clipped to a word boundary."""
    if overlap_chars <= 0 or len(chunk) <= overlap_chars:
        return chunk
    tail = chunk[-overlap_chars:]
    # Snap to next word boundary so we don't start mid-word.
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def _hard_split(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Last-resort splitter when a single sentence exceeds max_chars."""
    step = max_chars - overlap_chars
    return [text[i : i + max_chars] for i in range(0, len(text), max(step, 1))]


def _make_chunk(text: str, index: int) -> ChunkData:
    return ChunkData(
        text=text,
        chunk_index=index,
        token_count=max(1, len(text) // _CHARS_PER_TOKEN),
        metadata={},
    )


# ==========================================================================
# pipeline.py
# ==========================================================================


OWNER_TYPES: tuple[str, ...] = ("conference", "messaging", "sme_bio", "audience", "talk")


VALID_OWNER_TYPES = frozenset(OWNER_TYPES)


async def get_active_embedding_model(db: AsyncSession) -> EmbeddingModel:
    """Return the row in ``vectors.embedding_models`` with ``is_active=true``.

    Raises ``RuntimeError`` if zero or more-than-one are active.
    """
    result = await db.execute(select(EmbeddingModel).where(EmbeddingModel.is_active.is_(True)))
    rows = list(result.scalars().all())
    if not rows:
        raise RuntimeError(
            "no active embedding model — vectors.embedding_models has no is_active=true row. "
            "Did the seed migration run? (`make migrate`)"
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
        extra_metadata: merged into each chunk's ``chunk_metadata``. The PDF path
                        will pass page numbers / section headings here.
        client: override the LLM client (for tests).

    Returns:
        The number of chunks inserted (0 for empty/whitespace input).
    """
    if owner_type not in VALID_OWNER_TYPES:
        raise ValueError(f"invalid owner_type {owner_type!r}; valid: {sorted(VALID_OWNER_TYPES)}")

    model_row = await get_active_embedding_model(db)

    # Delete prior chunks for this owner under the active model. Other-model
    # chunks (during rollovers) stay until a re-embed catches them.
    await db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.owner_type == owner_type,
            DocumentChunk.owner_id == owner_id,
            DocumentChunk.embedding_model_id == model_row.id,
        )
    )

    # Chunk size rides settings so it can track the active embedding
    # model's serving context window (v2-moe on LiteMaaS caps at 512
    # tokens — the old 3000-char default overflowed it).
    _s = get_settings()
    chunks: list[ChunkData] = chunk_text(
        text,
        max_chars=_s.embed_chunk_max_chars,
        overlap_chars=_s.embed_chunk_overlap_chars,
    )
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


# ==========================================================================
# search.py
# ==========================================================================


class ChunkHit(NamedTuple):
    """A chunk and how close it actually was.

    The similarity is returned rather than attached to the ORM row. It used
    to be neither: ``similar_chunks`` returned bare rows and two consumers
    read ``getattr(chunk, "__cosine_similarity__", 0.0)`` — an attribute
    nothing ever set. Both silently got 0.0 for every hit, so the agent's
    cross-owner-type merge sorted by a constant (no ordering at all) and the
    brief picked its "most relevant" documents by dict insertion order. No
    exception, plausible-looking output, and a docstring in retrieval.py
    asserting the annotation happened.

    A value you must remember to attach is a contract that will be broken.
    A value in the return type cannot be.
    """

    chunk: DocumentChunk
    similarity: float


def _similarity_from_distance(distance: float) -> float:
    """pgvector returns cosine DISTANCE (0 = identical). Flip and clamp.

    Negative similarities are possible in principle but not for normalised
    embeddings, so they are clamped rather than surfaced.
    """
    sim = 1.0 - float(distance)
    return 0.0 if sim < 0.0 else 1.0 if sim > 1.0 else sim


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
) -> list[ChunkHit]:
    """Embed `query`, return the k chunks closest to it by cosine distance.

    Optionally filter by `owner_types` (e.g. ``["messaging"]`` for the fit signal
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
            decay. Pass False from background jobs / admin views.
        client: override the LLM client (for tests).

    Returns:
        Up to k :class:`ChunkHit` pairs, ordered closest-first.
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

    # pgvector exposes .cosine_distance(other) on Vector columns. Lower is
    # closer. SELECT it as well as ordering by it: callers need to know HOW
    # close, not just the order, and computing it twice would be silly.
    distance = DocumentChunk.embedding.cosine_distance(query_vec).label("distance")
    stmt = (
        select(DocumentChunk, distance)
        .where(DocumentChunk.embedding_model_id == model_row.id)
        .order_by(distance)
        .limit(k)
    )
    if owner_types:
        stmt = stmt.where(DocumentChunk.owner_type.in_(list(owner_types)))
    if owner_ids:
        stmt = stmt.where(DocumentChunk.owner_id.in_(list(owner_ids)))

    result = await db.execute(stmt)
    hits = [
        ChunkHit(chunk=chunk, similarity=_similarity_from_distance(dist))
        for chunk, dist in result.all()
    ]

    # Bump last_used_at on the hits so the decay pass keeps fresh chunks
    # prominent. Skipped for admin/diagnostic searches to avoid polluting decay.
    if hits and bump_last_used:
        await db.execute(
            update(DocumentChunk)
            .where(DocumentChunk.id.in_([h.chunk.id for h in hits]))
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
