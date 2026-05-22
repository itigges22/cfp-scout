"""Stage B — Four-pillar alignment (plan 17).

For each strategic pillar, compute the mean cosine similarity between the
conference's chunks and that pillar's description + any supporting
messaging documents (via ``messaging_pillars``). Per-pillar score = top-K
mean across (conf_chunk, pillar_evidence_chunk) pairs; overall pillar
score = max across pillars.

**Graceful degrade**: phase 1 ships with pillars seeded via the XLSX
workbook (plan 31). If no ``strategic_pillars`` rows exist yet, this
stage returns ``score=1.0`` so the matcher doesn't reject every conference
before pillars are entered. That's the explicit phase-1 stance — a
no-pillars-yet stack should still surface candidates for review.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import StrategicPillar
from app.db.models.junctions import MessagingPillar
from app.db.models.vectors import DocumentChunk
from app.services.llm import EmbeddingRequest, get_llm_client
from app.services.matcher._scoring import clamp01, topk_max, topk_mean

log = structlog.get_logger("scout.matcher.pillars")

TOPK_PILLAR = 5


@dataclass(slots=True, frozen=True)
class PillarHit:
    pillar_id: str
    pillar_name: str
    score: float


@dataclass(slots=True)
class PillarStageResult:
    score: float  # overall = max of per-pillar
    per_pillar: list[PillarHit]
    matched_pillar_id: str | None
    matched_pillar_name: str | None


async def stage_b_pillar_alignment(db: AsyncSession, conference_id: UUID) -> PillarStageResult:
    """Compute pillar alignment for ``conference_id``.

    Returns the per-pillar breakdown + the matched (top) pillar — the
    rationale stage uses both.
    """
    pillars = (
        (await db.execute(select(StrategicPillar).order_by(StrategicPillar.display_order)))
        .scalars()
        .all()
    )
    if not pillars:
        # See module docstring: don't penalize when the team hasn't seeded
        # pillars yet.
        log.info("matcher.pillars.none_configured", conference_id=str(conference_id))
        return PillarStageResult(
            score=1.0,
            per_pillar=[],
            matched_pillar_id=None,
            matched_pillar_name=None,
        )

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
        log.info("matcher.pillars.no_conference_chunks", conference_id=str(conference_id))
        return PillarStageResult(
            score=0.0,
            per_pillar=[],
            matched_pillar_id=None,
            matched_pillar_name=None,
        )

    # Pre-fetch the messaging chunks linked to each pillar (via the
    # messaging_pillars junction), in one query.
    msg_q = await db.execute(
        select(MessagingPillar.pillar_id, DocumentChunk).join(
            DocumentChunk,
            (DocumentChunk.owner_id == MessagingPillar.messaging_document_id)
            & (DocumentChunk.owner_type == "messaging"),
        )
    )
    pillar_msg_chunks: dict[UUID, list[DocumentChunk]] = {}
    for pid, chunk in msg_q.all():
        pillar_msg_chunks.setdefault(pid, []).append(chunk)

    # Embed each pillar description once (1 LLM call per pillar; nomic on
    # LLM API is cheap and the result is the same every run). Could be cached
    # in ``vectors.document_chunks`` later, but for phase 1 the volume is
    # 4-ish rows.
    client = get_llm_client()
    pillar_desc_vecs: dict[UUID, list[float]] = {}
    desc_embed = await client.embed(
        EmbeddingRequest(
            texts=[f"{p.name}: {p.description}" for p in pillars],
            purpose="embed:pillar_desc",
        ),
        db=db,
    )
    for pillar, vec in zip(pillars, desc_embed.vectors, strict=False):
        pillar_desc_vecs[pillar.id] = vec

    per_pillar: list[PillarHit] = []
    for p in pillars:
        # Evidence vectors = pillar description vec + each supporting
        # messaging chunk.
        evidence_vecs: list[list[float]] = [pillar_desc_vecs[p.id]]
        for mc in pillar_msg_chunks.get(p.id, []):
            if mc.embedding is not None:
                evidence_vecs.append(mc.embedding)

        sims: list[float] = []
        for cc in conf_chunks:
            if cc.embedding is None:
                continue
            for ev in evidence_vecs:
                sims.append(_cosine(cc.embedding, ev))
        # Top-K mean per pillar.
        score = clamp01(topk_mean(sims, k=TOPK_PILLAR))
        per_pillar.append(PillarHit(pillar_id=str(p.id), pillar_name=p.name, score=score))

    # Overall = max across pillars; record which one won.
    if per_pillar:
        winner = max(per_pillar, key=lambda h: h.score)
        overall = clamp01(topk_max(h.score for h in per_pillar))
    else:
        winner = None
        overall = 0.0

    log.info(
        "matcher.pillars.scored",
        conference_id=str(conference_id),
        overall=round(overall, 4),
        winner=winner.pillar_name if winner else None,
    )
    return PillarStageResult(
        score=overall,
        per_pillar=per_pillar,
        matched_pillar_id=winner.pillar_id if winner else None,
        matched_pillar_name=winner.pillar_name if winner else None,
    )


def _cosine(a, b) -> float:
    if a is None or b is None:
        return 0.0
    s = 0.0
    for x, y in zip(a, b, strict=False):
        s += float(x) * float(y)
    return clamp01(s)
