"""Retrieval layer for the agent (plan 22).

Wraps :func:`app.services.embeddings.search.similar_chunks` with a small
amount of post-processing:

  * Dedup by ``owner_id`` so one verbose owner can't crowd out the rest.
  * Compose human-friendly source labels (e.g. "Conference: NeurIPS 2027",
    "Messaging: team positioning") for the UI citation chips.
  * Compute the numbered snippet text the prompt + UI both reference.

Single owner-type set per call — keeps the embedding cost predictable.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    AudienceProfile,
    Conference,
    MessagingDocument,
    Sme,
    StrategicPillar,
)
from app.db.models.vectors import DocumentChunk
from app.services.embeddings import similar_chunks

log = structlog.get_logger("scout.agent.retrieval")

# Default owner_types for an open-ended question. Order doesn't matter —
# we sort by similarity after retrieval.
DEFAULT_OWNER_TYPES: list[str] = [
    "conference",
    "messaging",
    "sme_bio",
    "audience",
]

# How long each snippet body is. Keeps the prompt + the rendered chip both
# reasonable.
SNIPPET_CHARS = 320


@dataclass(slots=True, frozen=True)
class RetrievedSnippet:
    """One numbered retrieval hit."""

    index: int  # 1-based; matches [n] in the prompt
    chunk_id: str
    owner_type: str
    owner_id: str
    similarity: float
    label: str  # human-friendly source name
    text: str  # the actual snippet body (capped to SNIPPET_CHARS)


async def retrieve_for_question(
    db: AsyncSession,
    *,
    question: str,
    owner_types: list[str] | None = None,
    k: int = 16,
    k_per_type: int = 4,
) -> list[RetrievedSnippet]:
    """Retrieve numbered snippets for ``question``.

    Stratified by owner_type so no single category dominates the context
    window. The DB has ~553 conferences, ~16 SMEs, ~21 audiences, ~6
    messaging docs — without stratification, a flat top-k returns 6
    conferences for almost any query and the agent never sees SMEs.

    Behaviour:
      * Embeds ``question`` ONCE via :mod:`.similar_chunks` per owner type
        (cost-accounted as ``embed:agent_query``).
      * Pulls ``k_per_type`` chunks per type independently.
      * Concats, dedupes by (owner_type, owner_id), sorts by similarity,
        truncates to ``k``.
      * Hydrates a friendly label per owner (one batched query per
        owner_type).
    """
    if not question.strip():
        return []

    types = owner_types or DEFAULT_OWNER_TYPES

    # Per-type retrieval — serial because asyncpg can't multiplex queries
    # on a single connection (which is what the request's DbSession is).
    # The embedding call is cached by the LLM client after the first hit,
    # so the per-type cost is dominated by the cheap cosine SELECTs.
    per_type_hits: list[list[DocumentChunk]] = []
    for t in types:
        hits = await similar_chunks(
            db,
            query=question,
            owner_types=[t],
            k=k_per_type,
            purpose="embed:agent_query",
            bump_last_used=True,
        )
        per_type_hits.append(hits)

    # Flatten + sort by similarity (closest first). _similarity_of pulls
    # the __cosine_similarity__ attr set by similar_chunks.
    combined: list[DocumentChunk] = []
    for hits in per_type_hits:
        combined.extend(hits)
    if not combined:
        return []
    combined.sort(key=_similarity_of, reverse=True)

    # Dedup: at most ONE chunk per (owner_type, owner_id) so a long PDF
    # doesn't dominate. Cap at k overall.
    seen: set[tuple[str, str]] = set()
    keep: list[DocumentChunk] = []
    for c in combined:
        key = (c.owner_type, str(c.owner_id))
        if key in seen:
            continue
        seen.add(key)
        keep.append(c)
        if len(keep) >= k:
            break

    labels = await _resolve_labels(db, keep)

    snippets: list[RetrievedSnippet] = []
    for i, c in enumerate(keep, start=1):
        text = (c.text or "").strip()
        if len(text) > SNIPPET_CHARS:
            text = text[: SNIPPET_CHARS - 1].rstrip() + "…"
        snippets.append(
            RetrievedSnippet(
                index=i,
                chunk_id=str(c.id),
                owner_type=c.owner_type,
                owner_id=str(c.owner_id),
                similarity=round(_similarity_of(c), 4),
                label=labels.get((c.owner_type, str(c.owner_id)), c.owner_type),
                text=text,
            )
        )
    log.info(
        "agent.retrieval",
        question_preview=question[:80],
        n_hits=len(hits),
        n_kept=len(snippets),
    )
    return snippets


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _similarity_of(chunk: DocumentChunk) -> float:
    """Pull the matcher-style similarity off the chunk.

    ``similar_chunks`` annotates each row with a ``__cosine_similarity__``
    attribute when available; falls back to 0 so the field is always
    sortable. We don't rely on it for ordering (caller already does), just
    for surfacing in the API response.
    """
    return float(getattr(chunk, "__cosine_similarity__", 0.0) or 0.0)


async def _resolve_labels(
    db: AsyncSession, chunks: list[DocumentChunk]
) -> dict[tuple[str, str], str]:
    """Return a {(owner_type, owner_id): "Conference: NeurIPS 2027", ...} map.

    One query per distinct owner_type — small N per call.
    """
    by_type: dict[str, list[str]] = {}
    for c in chunks:
        by_type.setdefault(c.owner_type, []).append(str(c.owner_id))

    out: dict[tuple[str, str], str] = {}

    if ids := by_type.get("conference"):
        rows = (
            await db.execute(select(Conference.id, Conference.name).where(Conference.id.in_(ids)))
        ).all()
        for cid, name in rows:
            out[("conference", str(cid))] = f"Conference: {name}"

    if ids := by_type.get("messaging"):
        rows = (
            await db.execute(
                select(MessagingDocument.id, MessagingDocument.title).where(
                    MessagingDocument.id.in_(ids)
                )
            )
        ).all()
        for mid, title in rows:
            out[("messaging", str(mid))] = f"Messaging: {title}"

    if ids := by_type.get("audience"):
        rows = (
            await db.execute(
                select(AudienceProfile.id, AudienceProfile.name).where(AudienceProfile.id.in_(ids))
            )
        ).all()
        for aid, name in rows:
            out[("audience", str(aid))] = f"Audience: {name}"

    if ids := by_type.get("sme_bio"):
        rows = (await db.execute(select(Sme.id, Sme.full_name).where(Sme.id.in_(ids)))).all()
        for sid, name in rows:
            out[("sme_bio", str(sid))] = f"SME: {name}"

    if ids := by_type.get("pillar"):
        rows = (
            await db.execute(
                select(StrategicPillar.id, StrategicPillar.name).where(StrategicPillar.id.in_(ids))
            )
        ).all()
        for pid, name in rows:
            out[("pillar", str(pid))] = f"Pillar: {name}"

    return out
