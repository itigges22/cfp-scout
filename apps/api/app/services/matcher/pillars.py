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
from app.services.matcher._scoring import clamp01, rescale_score, topk_max, topk_mean

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

    # Embed each pillar's text once (1 LLM call per pillar; nomic is
    # cheap). Prefers the long-form ``enriched_description`` (extracted
    # from the operator's messaging documents) over the short tagline
    # ``description`` — the short version has nowhere near enough
    # discriminative vocabulary for cosine to separate "genuinely fits
    # this pillar" from "AI-adjacent in general," so without enrichment
    # stage B saturates at 100% for almost every conference.
    client = get_llm_client()
    pillar_desc_vecs: dict[UUID, list[float]] = {}
    pillar_texts = [
        f"{p.name}: {p.enriched_description or p.description}" for p in pillars
    ]
    desc_embed = await client.embed(
        EmbeddingRequest(
            texts=pillar_texts,
            purpose="embed:pillar_desc",
        ),
        db=db,
    )
    for pillar, vec in zip(pillars, desc_embed.vectors, strict=False):
        pillar_desc_vecs[pillar.id] = vec

    # Per-pillar raw cosines (top-K mean across the conf × evidence
    # pairs for THIS pillar). Keep RAW (un-rescaled) so we can compute
    # distinctiveness across pillars below — rescaling each one
    # independently and taking max saturates at 100% for every AI
    # conference because at least one pillar always clears the ceiling
    # in nomic-embed-text's narrow cosine band.
    per_pillar_raw: list[tuple[StrategicPillar, float]] = []
    for p in pillars:
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
        per_pillar_raw.append((p, topk_mean(sims, k=TOPK_PILLAR)))

    # Distinctiveness-weighted aggregation via softmax. We want:
    #   - a conference peaked on ONE pillar (high cosine to it, lower
    #     to the rest) → high score
    #   - a conference uniformly matching ALL pillars (generic AI
    #     adjacency) → moderate score
    #   - a conference matching NO pillars (off-topic) → low score
    #
    # Plain MAX-across-pillars produces 100% for everyone because the
    # embedder's cosine band is tight (post-enrichment all 4 pillar
    # cosines land in [0.55, 0.75]) and one pillar always clears any
    # ceiling. Softmax with a high temperature amplifies the tiny
    # absolute differences within that tight band into a meaningful
    # peakedness signal: 0.25 if all 4 pillars cosine identically,
    # approaching 1.0 if one dominates.
    import math

    raw_cosines = [c for _, c in per_pillar_raw]
    n = len(raw_cosines)
    sorted_raw = sorted(raw_cosines, reverse=True)
    top_raw = sorted_raw[0] if sorted_raw else 0.0
    if len(sorted_raw) > 1:
        mean_others = sum(sorted_raw[1:]) / (len(sorted_raw) - 1)
    else:
        mean_others = 0.0
    # Softmax peakedness. T=50 because cosines differ by ~0.05 in
    # this corpus; exp(50 × 0.05) ≈ 12 gives meaningful amplification.
    PEAK_T = 50.0
    if raw_cosines:
        # Subtract max for numerical stability before exp.
        shifted = [c - top_raw for c in raw_cosines]
        exp_vals = [math.exp(PEAK_T * s) for s in shifted]
        total = sum(exp_vals)
        softmax = [e / total for e in exp_vals] if total > 0 else [1.0 / n] * n
        peakedness = max(softmax)  # in [1/N, 1.0]
    else:
        peakedness = 0.0
    # Normalize peakedness to [0, 1]: uniform → 0, perfect peak → 1.
    norm_peakedness = (
        max(0.0, (peakedness - 1.0 / n) / (1.0 - 1.0 / n)) if n > 1 else 1.0
    )
    # Composite mixes the absolute top cosine with the normalized
    # peakedness. Weights: 40% absolute scale, 60% peakedness — the
    # peakedness penalty is what breaks the everyone-at-100% bug, so
    # it gets the bigger weight.
    composite_raw = top_raw * (0.4 + 0.6 * norm_peakedness)

    # Rescale into [0, 1]. With top_raw typically ~0.6-0.7 and
    # norm_peakedness in [0, 1], composite_raw spans roughly [0.24, 0.7].
    # Floor 0.25 / ceiling 0.65 puts uniform-AI conferences around
    # 0%, mildly-peaked ones around 40-60%, strongly-peaked ones near
    # 100%, and off-topic events near 0%.
    overall = rescale_score(composite_raw, floor=0.25, ceiling=0.65)

    # Per-pillar PillarHit list — each pillar's INDIVIDUAL rescaled
    # score (with the same band) so the UI still has per-pillar values
    # for the breakdown card.
    # Per-pillar UI breakdown — use the softmax weights so the user
    # sees which pillar(s) the conference is leaning toward. A pillar
    # that softmax says is the dominant one shows close to 1.0; the
    # others show smaller fractions.
    per_pillar: list[PillarHit] = [
        PillarHit(
            pillar_id=str(p.id),
            pillar_name=p.name,
            score=softmax[i] if i < len(softmax) else 0.0,
        )
        for i, (p, c) in enumerate(per_pillar_raw)
    ]
    winner = max(per_pillar, key=lambda h: h.score) if per_pillar else None

    log.info(
        "matcher.pillars.scored",
        conference_id=str(conference_id),
        overall=round(overall, 4),
        top_raw=round(top_raw, 4),
        mean_others=round(mean_others, 4),
        peakedness=round(peakedness, 4),
        norm_peakedness=round(norm_peakedness, 4),
        composite_raw=round(composite_raw, 4),
        winner=winner.pillar_name if winner else None,
    )
    return PillarStageResult(
        score=overall,
        per_pillar=per_pillar,
        matched_pillar_id=winner.pillar_id if winner else None,
        matched_pillar_name=winner.pillar_name if winner else None,
    )


def _cosine(a, b) -> float:
    """Cosine similarity with proper normalization. See the matching
    function in matcher/messaging.py for the bug history — the previous
    bare-dot-product version was returning ~250 for every pair, clamp01
    squashed to 1.0, every pillar saturated."""
    if a is None or b is None:
        return 0.0
    from math import sqrt

    dot = 0.0
    mag_a = 0.0
    mag_b = 0.0
    for x, y in zip(a, b, strict=False):
        fx, fy = float(x), float(y)
        dot += fx * fy
        mag_a += fx * fx
        mag_b += fy * fy
    if mag_a <= 0 or mag_b <= 0:
        return 0.0
    return clamp01(dot / (sqrt(mag_a) * sqrt(mag_b)))
