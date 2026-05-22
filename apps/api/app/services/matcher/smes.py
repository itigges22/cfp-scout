"""Stage C — SME match (plan 17).

Plan 17 delegates the ranking to plan 18's bio-similarity matcher, which
isn't built yet. Until then, we use the graph-overlap signal from plan 16:
``candidate_smes_for_conference`` returns ranked SMEs by shared topics +
audiences. Plan 18 will swap in a richer combined score.

The stage returns ``(top_sme_score, [recommended_ids], [snippets_for_rationale])``.
``top_sme_score`` is the highest individual SME score (used by the gate);
``recommended_ids`` are the IDs above the gate, in rank order.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from app.services.graph import candidate_smes_for_conference, load_graph
from app.services.matcher._scoring import clamp01

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
    score: float                   # max individual SME score
    recommendations: list[SmeRecommendation]


async def stage_c_sme_match(conference_id: UUID, gate: float) -> SmeStageResult:
    """Return top-K SME candidates + max score for ``conference_id``.

    Pulled from the in-memory graph (60s TTL cache), so this is cheap once
    plan 16's loader has warmed.
    """
    graph = await load_graph()
    raw = candidate_smes_for_conference(graph, str(conference_id), k=K_CANDIDATES)
    recs = [
        SmeRecommendation(
            sme_id=r.sme_id,
            label=r.label,
            team=r.team,
            score=clamp01(r.score),
        )
        for r in raw
    ]
    above_gate = [r for r in recs if r.score >= gate]
    top = max((r.score for r in recs), default=0.0)
    log.info(
        "matcher.smes.scored",
        conference_id=str(conference_id),
        top=round(top, 4),
        n_above_gate=len(above_gate),
        n_candidates=len(recs),
    )
    return SmeStageResult(score=clamp01(top), recommendations=above_gate or recs[:1])
