"""Stage A — Messaging fit (plan 17).

The gate-keeping stage. Computes mean cosine similarity between the
conference's chunks and the messaging-document chunks; conferences below
``MATCH_M_GATE`` are excluded from default dashboard views.

Implementation: one SQL query that, for each conference chunk, finds the
top-N most-similar messaging chunks via pgvector's cosine distance, then
aggregates per the configured strategy. Returns a typed score + the snippet
list the rationale stage uses for citations.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vectors import DocumentChunk
from app.services.matcher._scoring import (
    apply_chunk_decay,
    clamp01,
    cosine_from_distance,
    rescale_score,
    topk_mean,
)

log = structlog.get_logger("scout.matcher.messaging")

# K for top-K mean. Plan 17 specifies 10; keep at module level so tests can
# monkeypatch without rebuilding settings.
TOPK_MESSAGING = 10


@dataclass(slots=True, frozen=True)
class MessagingSnippet:
    """One messaging-chunk hit; surfaced to the rationale stage for citation."""

    chunk_id: str
    owner_id: str
    similarity: float
    text_preview: str


@dataclass(slots=True)
class MessagingStageResult:
    score: float
    n_compared: int
    snippets: list[MessagingSnippet]


async def stage_a_messaging_fit(db: AsyncSession, conference_id: UUID) -> MessagingStageResult:
    """Compute messaging-fit score for ``conference_id``.

    Score = mean of the top-K cosine similarities across all (conf_chunk,
    messaging_chunk) pairs above a tiny noise floor. If the conference has
    no chunks (extraction-time embed failed), score=0 with empty snippets.
    """
    # Conference chunks. If none, exit early — this is the early signal
    # that the embed-on-extract step didn't run for this conference.
    conf_chunks = (
        (
            await db.execute(
                select(DocumentChunk).where(
                    DocumentChunk.owner_type == "conference",
                    DocumentChunk.owner_id == conference_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not conf_chunks:
        log.info("matcher.messaging.no_conference_chunks", conference_id=str(conference_id))
        return MessagingStageResult(score=0.0, n_compared=0, snippets=[])

    # Pull all messaging chunks once. Phase-1 messaging volume is tiny
    # (one PDF = ~12 chunks), so a single fetch + in-memory dot is faster
    # than N round-trips to pgvector. If volume grows, swap to a single
    # SQL query that flattens conf chunks via UNNEST and joins on
    # cosine_distance ORDER BY LIMIT N.
    messaging_chunks = (
        (await db.execute(select(DocumentChunk).where(DocumentChunk.owner_type == "messaging")))
        .scalars()
        .all()
    )
    if not messaging_chunks:
        log.info("matcher.messaging.no_messaging_chunks")
        return MessagingStageResult(score=0.0, n_compared=0, snippets=[])

    # Cross-pair similarities. Each conf chunk against each messaging chunk.
    # When DECAY_ENABLED, we multiply the raw cosine by min(conf, msg)
    # freshness so a stale chunk pair contributes less. Picking the MIN of
    # the two freshnesses (vs product or mean) keeps the math intuitive:
    # one stale side is enough to discount the pair.
    all_pairs: list[tuple[float, DocumentChunk]] = []
    for cc in conf_chunks:
        for mc in messaging_chunks:
            sim = _cosine_sim(cc.embedding, mc.embedding)
            sim = apply_chunk_decay(sim, cc)
            sim = apply_chunk_decay(sim, mc)
            all_pairs.append((sim, mc))

    # Top-K mean of RAW cosines, then rescale against the empirical
    # floor/ceiling so the score actually spreads out across the
    # [0, 1] range instead of saturating at ~0.9996 for every event.
    # See rescale_score docstring for the math.
    all_pairs.sort(key=lambda p: p[0], reverse=True)
    top = all_pairs[:TOPK_MESSAGING]
    raw_topk_mean = topk_mean([p[0] for p in top], k=TOPK_MESSAGING)
    score = rescale_score(raw_topk_mean)

    snippets = [
        MessagingSnippet(
            chunk_id=str(mc.id),
            owner_id=str(mc.owner_id),
            similarity=round(sim, 4),
            text_preview=mc.text[:200],
        )
        for sim, mc in top
    ]

    log.info(
        "matcher.messaging.scored",
        conference_id=str(conference_id),
        score=round(score, 4),
        n_conf_chunks=len(conf_chunks),
        n_messaging_chunks=len(messaging_chunks),
        n_pairs=len(all_pairs),
    )
    return MessagingStageResult(score=score, n_compared=len(all_pairs), snippets=snippets)


def _cosine_sim(a, b) -> float:
    """Cosine similarity over pgvector-backed lists.

    pgvector returns Python lists when read into ORM; both vectors are
    normalized (nomic-embed-text-v1-5 emits unit vectors), so a dot product
    equals the cosine. We compute it manually to avoid pulling numpy.
    """
    if a is None or b is None:
        return 0.0
    s = 0.0
    for x, y in zip(a, b, strict=False):
        s += float(x) * float(y)
    return clamp01(s)


# Re-export so the pipeline doesn't have to import from a private module.
__all__ = [
    "TOPK_MESSAGING",
    "MessagingSnippet",
    "MessagingStageResult",
    "stage_a_messaging_fit",
]

# Suppress unused-import lints — `cosine_from_distance` is part of the
# matcher's public scoring surface even if this stage doesn't use it.
_ = cosine_from_distance
