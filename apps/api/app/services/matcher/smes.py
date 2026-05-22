"""Stage C — SME match (plan 17 + plan 18).

Thin wrapper over the per-dimension ranker in :mod:`.sme_ranker`. Keeps
the existing ``SmeStageResult`` shape stable for the pipeline so the
plan-17 orchestrator didn't need to change.

The full per-dimension breakdown is exposed by
``GET /api/v1/conferences/{id}/smes`` (plan 18). The matcher's own
``recommended_sme_ids`` array stores only the composite scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matcher._scoring import clamp01
from app.services.matcher.sme_ranker import rank_smes_for_conference

log = structlog.get_logger("scout.matcher.smes")

K_CANDIDATES = 5


@dataclass(slots=True, frozen=True)
class SmeRecommendation:
    sme_id: str
    label: str
    team: str | None
    score: float


@dataclass(slots=True)
class SmeStageResult:
    score: float                            # max composite score
    recommendations: list[SmeRecommendation]


async def stage_c_sme_match(
    db: AsyncSession, conference_id: UUID, gate: float
) -> SmeStageResult:
    """Return the top-K SME recommendations for the matcher pipeline."""
    ranker = await rank_smes_for_conference(
        db, conference_id, k=K_CANDIDATES, gate=gate
    )

    above = ranker.above_gate
    if above:
        recs = above
        top = max(b.composite for b in above)
    elif ranker.near_misses:
        # Plan 17 routes to ``needs_sme_review`` when nothing clears the
        # gate. Surface the near-misses so the dashboard still has
        # candidates for the admin to consider.
        recs = ranker.near_misses
        top = max(b.composite for b in recs)
    else:
        recs = []
        top = 0.0

    log.info(
        "matcher.smes.scored",
        conference_id=str(conference_id),
        top=round(top, 4),
        n_above_gate=len(above),
        n_near_misses=len(ranker.near_misses),
    )
    return SmeStageResult(
        score=clamp01(top),
        recommendations=[
            SmeRecommendation(
                sme_id=b.sme_id,
                label=b.full_name,
                team=b.team,
                score=b.composite,
            )
            for b in recs
        ],
    )
