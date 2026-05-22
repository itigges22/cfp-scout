"""SME ranker — mechanical per-dimension score (plan 18).

Refines the graph-only signal from plan 16 / Stage C of plan 17 with a
weighted breakdown across five dimensions. The qualitative LLM-generated
"fit narrative" is plan 19's job and runs only for the top 3 per conference.

Dimensions
----------
1. **Topic overlap** — Jaccard between the conference's topic set and the
   SME's topic set (both via junction tables; ignores pending-review topics).
2. **Audience overlap** — Jaccard between conference_audiences and
   sme_audiences. Conference-side audiences are populated by future
   matcher work (plan 16 pass 2 / plan 17 pass 2); for now this is 0
   for every conference, which still allows tuning + bio + location to
   rank SMEs.
3. **Bio similarity** — cosine between the conference chunks
   (owner_type='conference') and the SME bio chunks
   (owner_type='sme_bio'). We take the mean of the top-3 pair similarities
   — the same shape as the messaging stage but per-SME.
4. **Location proximity** —
   virtual / same country → 1.0; same continent → 0.6; otherwise → 0.3.
   Continent map lives in :mod:`._continents`.
5. **Past attendance bonus** — +1.0 if this SME has a ``past_conferences``
   row whose series matches the candidate conference's series. Series
   linking lives in plan 23; until then this is 0.

Composite = sum of per-dimension * env weight (settings.sme_w_*).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, PastConference, Sme, Topic
from app.db.models.junctions import (
    ConferenceAudience,
    ConferenceTopic,
    SmeAudience,
    SmeTopic,
)
from app.db.models.vectors import DocumentChunk
from app.services.matcher._continents import continent_for
from app.services.matcher._scoring import clamp01
from app.settings import get_settings

log = structlog.get_logger("scout.matcher.sme_ranker")

TOPK_BIO = 3


@dataclass(slots=True, frozen=True)
class DimensionScores:
    topic_overlap: float
    audience_overlap: float
    bio_similarity: float
    location: float
    past_attendance: float


@dataclass(slots=True)
class SmeBreakdown:
    """Per-SME score with each dimension surfaced.

    Returned by :func:`rank_smes_for_conference`. Designed for direct
    JSON serialization by the API route.
    """

    sme_id: str
    full_name: str
    team: str
    location_country: str | None
    location_city: str | None
    is_external: bool  # True when team != 'team' (UI labeling hint)
    dimensions: DimensionScores
    composite: float
    above_gate: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dimensions"] = asdict(self.dimensions)
        return d


@dataclass(slots=True)
class RankerResult:
    """Bundles the ranked list + the "near misses" (just below gate)."""

    above_gate: list[SmeBreakdown] = field(default_factory=list)
    near_misses: list[SmeBreakdown] = field(default_factory=list)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
async def rank_smes_for_conference(
    db: AsyncSession,
    conference_id: UUID,
    *,
    k: int = 5,
    gate: float | None = None,
    near_miss_window: float = 0.10,
) -> RankerResult:
    """Rank active SMEs against ``conference_id``; return top-K above
    ``gate`` plus near-misses (within ``near_miss_window`` below the gate).
    """
    settings = get_settings()
    gate = gate if gate is not None else settings.match_s_gate

    conference = await db.get(Conference, conference_id)
    if conference is None:
        return RankerResult()

    # Pre-load context the inner loop reuses across every SME.
    ctx = await _load_conference_context(db, conference)

    # Active SMEs only — inactive ones never appear.
    sme_rows = (await db.execute(select(Sme).where(Sme.is_active.is_(True)))).scalars().all()
    if not sme_rows:
        return RankerResult()

    scored: list[SmeBreakdown] = []
    for sme in sme_rows:
        b = await _score_one(db, conference, sme, ctx, settings)
        b.above_gate = b.composite >= gate
        scored.append(b)

    scored.sort(key=lambda b: b.composite, reverse=True)

    above = [b for b in scored if b.above_gate][:k]
    if above:
        # Near misses = anyone with composite in [gate - window, gate).
        nm_floor = gate - near_miss_window
        near = [b for b in scored if (not b.above_gate) and b.composite >= nm_floor][:k]
    else:
        # Nobody cleared the gate. Surface the top-K candidates anyway —
        # the matcher's "needs_sme_review" status uses these to populate
        # the dashboard so admins can review borderline picks.
        near = scored[:k]

    log.info(
        "matcher.sme_ranker.done",
        conference_id=str(conference_id),
        n_smes=len(sme_rows),
        n_above_gate=len(above),
        n_near_misses=len(near),
        top_composite=round(scored[0].composite, 4) if scored else 0.0,
    )
    return RankerResult(above_gate=above, near_misses=near)


# --------------------------------------------------------------------------
# Conference-side context (loaded once per call)
# --------------------------------------------------------------------------
@dataclass(slots=True)
class _ConferenceContext:
    topic_ids: set[UUID]
    audience_ids: set[UUID]
    chunks: list[DocumentChunk]
    series_id: UUID | None


async def _load_conference_context(db: AsyncSession, conference: Conference) -> _ConferenceContext:
    # Topic set (active topics only — pending-review ones don't count).
    topic_rows = (
        await db.execute(
            select(ConferenceTopic.topic_id, Topic.is_active, Topic.pending_review)
            .join(Topic, Topic.id == ConferenceTopic.topic_id)
            .where(ConferenceTopic.conference_id == conference.id)
        )
    ).all()
    topic_ids = {tid for tid, active, pending in topic_rows if active and not pending}

    # Audience set.
    audience_ids = {
        aid
        for (aid,) in (
            await db.execute(
                select(ConferenceAudience.audience_id).where(
                    ConferenceAudience.conference_id == conference.id
                )
            )
        ).all()
    }

    chunks = (
        (
            await db.execute(
                select(DocumentChunk).where(
                    DocumentChunk.owner_type == "conference",
                    DocumentChunk.owner_id == conference.id,
                )
            )
        )
        .scalars()
        .all()
    )

    return _ConferenceContext(
        topic_ids=topic_ids,
        audience_ids=audience_ids,
        chunks=chunks,
        series_id=conference.series_id,
    )


# --------------------------------------------------------------------------
# Per-SME scoring
# --------------------------------------------------------------------------
async def _score_one(
    db: AsyncSession,
    conference: Conference,
    sme: Sme,
    ctx: _ConferenceContext,
    settings,
) -> SmeBreakdown:
    # ---- Topic overlap (Jaccard) -----------------------------------
    sme_topic_ids = {
        tid
        for (tid,) in (
            await db.execute(select(SmeTopic.topic_id).where(SmeTopic.sme_id == sme.id))
        ).all()
    }
    topic_score = _jaccard(ctx.topic_ids, sme_topic_ids)

    # ---- Audience overlap (Jaccard) --------------------------------
    sme_audience_ids = {
        aid
        for (aid,) in (
            await db.execute(select(SmeAudience.audience_id).where(SmeAudience.sme_id == sme.id))
        ).all()
    }
    audience_score = _jaccard(ctx.audience_ids, sme_audience_ids)

    # ---- Bio similarity --------------------------------------------
    bio_score = await _bio_similarity(db, sme.id, ctx.chunks)

    # ---- Location proximity ----------------------------------------
    location_score = _location_score(
        conference_country=conference.location_country,
        conference_virtual=conference.is_virtual,
        sme_country=sme.location_country,
    )

    # ---- Past attendance bonus -------------------------------------
    past_score = await _past_attendance(db, sme.id, ctx.series_id)

    dims = DimensionScores(
        topic_overlap=round(topic_score, 4),
        audience_overlap=round(audience_score, 4),
        bio_similarity=round(bio_score, 4),
        location=round(location_score, 4),
        past_attendance=round(past_score, 4),
    )
    composite = clamp01(
        settings.sme_w_topic * topic_score
        + settings.sme_w_audience * audience_score
        + settings.sme_w_bio * bio_score
        + settings.sme_w_location * location_score
        + settings.sme_w_past * past_score
    )
    return SmeBreakdown(
        sme_id=str(sme.id),
        full_name=sme.full_name,
        team=sme.team,
        location_country=sme.location_country,
        location_city=sme.location_city,
        is_external=(sme.team.lower() != "daam"),
        dimensions=dims,
        composite=round(composite, 4),
        above_gate=False,  # filled by caller
    )


# --------------------------------------------------------------------------
# Dimension helpers
# --------------------------------------------------------------------------
def _jaccard(a: set, b: set) -> float:
    """Jaccard = |A∩B| / |A∪B|. Both empty → 0 (no signal, not 1.0)."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


async def _bio_similarity(
    db: AsyncSession, sme_id: UUID, conference_chunks: list[DocumentChunk]
) -> float:
    """Mean of top-3 pair cosines between conference chunks and the SME's
    bio chunks. 0.0 if either side has nothing."""
    if not conference_chunks:
        return 0.0
    bio_chunks = (
        (
            await db.execute(
                select(DocumentChunk).where(
                    DocumentChunk.owner_type == "sme_bio",
                    DocumentChunk.owner_id == sme_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not bio_chunks:
        return 0.0
    sims: list[float] = []
    for cc in conference_chunks:
        if cc.embedding is None:
            continue
        for bc in bio_chunks:
            if bc.embedding is None:
                continue
            sims.append(_cosine(cc.embedding, bc.embedding))
    if not sims:
        return 0.0
    top = sorted(sims, reverse=True)[:TOPK_BIO]
    return clamp01(sum(top) / len(top))


def _location_score(
    *,
    conference_country: str | None,
    conference_virtual: bool,
    sme_country: str | None,
) -> float:
    """Plan-18 location buckets."""
    if conference_virtual:
        return 1.0
    if not conference_country or not sme_country:
        return 0.3
    if conference_country.upper() == sme_country.upper():
        return 1.0
    a = continent_for(conference_country)
    b = continent_for(sme_country)
    if a and b and a == b:
        return 0.6
    return 0.3


async def _past_attendance(
    db: AsyncSession, sme_id: UUID, conference_series_id: UUID | None
) -> float:
    """1.0 if the SME has a past_conferences row whose series matches the
    candidate's series AND the SME's id appears in ``attended_sme_ids``.
    0 otherwise. Plan 23 wires the series linkage; until then this stays
    0 in practice (PastConference.series_id is None for manual entries)."""
    if conference_series_id is None:
        return 0.0
    # ANY(...) on a Postgres ARRAY column: SQLAlchemy's `.any_(value)` does
    # the equivalent of ``value = ANY(array)``.
    row = (
        await db.execute(
            select(PastConference.id)
            .where(PastConference.series_id == conference_series_id)
            .where(PastConference.attended_sme_ids.any(sme_id))
            .limit(1)
        )
    ).first()
    return 1.0 if row else 0.0


# --------------------------------------------------------------------------
# Math
# --------------------------------------------------------------------------
def _cosine(a, b) -> float:
    if a is None or b is None:
        return 0.0
    s = 0.0
    for x, y in zip(a, b, strict=False):
        s += float(x) * float(y)
    return clamp01(s)
