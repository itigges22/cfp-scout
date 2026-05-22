"""Multi-SME team recommendations (plan 32).

After the matcher (plan 17) scores individuals, this picks **complementary
teams** of size 1, 2, and 3 that maximize topic coverage while keeping
individual fit high. Pure algorithmic — no LLM, no extra cost.

Algorithm:

  1. Pull top-K candidates from plan 18's ranker (default K=10).
  2. For each team size n ∈ {1, 2, 3}, enumerate C(K, n) candidate teams.
  3. Score each team:

         team_score = α * avg_individual_fit
                    + β * topic_coverage_breadth
                    - γ * topic_redundancy
                    - δ * location_redundancy

     - **coverage_breadth** = (# distinct conference topics covered by AT
       LEAST ONE team member's primary topics) / (# conference topics).
     - **redundancy** = mean pairwise Jaccard similarity of team members'
       topic sets. High = overlapping experts.
     - **location_redundancy** = fraction of pairs sharing the same city
       for an in-person conference. Zero for virtual events.

  4. Pick the top-1 team for each size, persist to
     ``app.match_team_recommendations``.
  5. Generate a one-sentence templated rationale (no LLM):
     ``"Together they cover 5 of 6 conference topics: RAG, MLOps, …"``.

Idempotent on the ``(match_id, team_size)`` composite PK: re-running
deletes + reinserts the three rows for that match.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, Sme, Topic
from app.db.models.junctions import ConferenceTopic, SmeTopic
from app.db.models.matching import Match, MatchTeamRecommendation
from app.services.matcher import ALGORITHM_VERSION
from app.services.matcher.sme_ranker import (
    SmeBreakdown,
    rank_smes_for_conference,
)
from app.settings import get_settings

log = structlog.get_logger("scout.matcher.teams")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class TeamMember:
    sme_id: str
    full_name: str
    team: str
    is_external: bool
    individual_score: float
    location_city: str | None
    covered_topics: list[str]


@dataclass(slots=True)
class TeamPick:
    team_size: int
    sme_ids: list[str]
    team_score: float
    coverage_breadth: float
    redundancy: float
    rationale_text: str
    members: list[TeamMember] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass(slots=True)
class TeamRecommendations:
    conference_id: str
    by_size: dict[int, TeamPick] = field(default_factory=dict)
    candidate_count: int = 0
    algorithm_version: str = ALGORITHM_VERSION

    def to_dict(self) -> dict:
        return {
            "conference_id": self.conference_id,
            "algorithm_version": self.algorithm_version,
            "candidate_count": self.candidate_count,
            "by_size": {str(k): v.to_dict() for k, v in self.by_size.items()},
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def recommend_teams(db: AsyncSession, conference_id: UUID) -> TeamRecommendations:
    """Compute + persist team picks for sizes 1, 2, 3.

    Caller commits.
    """
    settings = get_settings()

    conference = await db.get(Conference, conference_id)
    if conference is None:
        return TeamRecommendations(conference_id=str(conference_id))

    # We need the matches row to anchor the team recommendations on.
    match = (
        await db.execute(
            select(Match)
            .where(Match.conference_id == conference_id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
        )
    ).scalar_one_or_none()
    if match is None:
        log.warning(
            "teams.no_match_row",
            conference_id=str(conference_id),
            algorithm_version=ALGORITHM_VERSION,
        )
        return TeamRecommendations(conference_id=str(conference_id))

    # Top-K candidates via plan-18's ranker.
    ranker = await rank_smes_for_conference(
        db,
        conference_id,
        k=settings.team_topk_candidates,
        gate=0.0,  # don't filter at the ranker level; team scoring can use everyone
    )
    candidates: list[SmeBreakdown] = (ranker.above_gate or []) + (ranker.near_misses or [])
    candidates = candidates[: settings.team_topk_candidates]

    # Cross-load conference topic IDs + member topic IDs in one pass.
    conf_topic_ids = await _conference_topic_ids(db, conference_id)
    member_topic_ids = await _sme_topic_ids(db, [UUID(c.sme_id) for c in candidates])
    sme_rows = await _sme_rows(db, [UUID(c.sme_id) for c in candidates])
    topic_name_by_id = await _topic_name_index(db, conf_topic_ids)

    out = TeamRecommendations(
        conference_id=str(conference_id),
        candidate_count=len(candidates),
    )

    # Score teams of each size. Skip sizes we can't fill (e.g., team of 3 with 2 candidates).
    is_virtual = bool(conference.is_virtual)
    for n in (1, 2, 3):
        if n > len(candidates):
            continue
        best = _best_team_of_size(
            candidates=candidates,
            n=n,
            conf_topic_ids=conf_topic_ids,
            member_topic_ids=member_topic_ids,
            sme_rows=sme_rows,
            settings=settings,
            is_virtual=is_virtual,
            topic_name_by_id=topic_name_by_id,
        )
        if best is not None:
            out.by_size[n] = best

    # Persist (idempotent on (match_id, team_size) composite PK).
    await db.execute(
        delete(MatchTeamRecommendation).where(MatchTeamRecommendation.match_id == match.id)
    )
    for n, pick in out.by_size.items():
        db.add(
            MatchTeamRecommendation(
                match_id=match.id,
                team_size=n,
                sme_ids=[UUID(sid) for sid in pick.sme_ids],
                team_score=pick.team_score,
                coverage_breadth=pick.coverage_breadth,
                redundancy=pick.redundancy,
                rationale_text=pick.rationale_text,
            )
        )
    await db.flush()

    log.info(
        "teams.done",
        conference_id=str(conference_id),
        candidate_count=len(candidates),
        sizes_computed=sorted(out.by_size.keys()),
    )
    return out


# ---------------------------------------------------------------------------
# Per-size best
# ---------------------------------------------------------------------------
def _best_team_of_size(
    *,
    candidates: list[SmeBreakdown],
    n: int,
    conf_topic_ids: set[UUID],
    member_topic_ids: dict[UUID, set[UUID]],
    sme_rows: dict[UUID, Sme],
    settings,
    is_virtual: bool,
    topic_name_by_id: dict[UUID, str],
) -> TeamPick | None:
    best: TeamPick | None = None
    best_score = float("-inf")

    for combo in combinations(candidates, n):
        sme_ids = [UUID(c.sme_id) for c in combo]
        topic_sets = [member_topic_ids.get(sid, set()) for sid in sme_ids]
        union = set().union(*topic_sets) if topic_sets else set()
        covered = union & conf_topic_ids if conf_topic_ids else set()

        # Coverage breadth: 0 when conference has no topics yet (we still
        # want to recommend SOMETHING — fall back to 1.0 so individual
        # fit dominates).
        coverage = len(covered) / len(conf_topic_ids) if conf_topic_ids else 1.0

        avg_fit = sum(c.composite for c in combo) / n

        redundancy = _redundancy(topic_sets)
        location_red = _location_redundancy(sme_ids, sme_rows, is_virtual)

        score = (
            settings.team_w_individual * avg_fit
            + settings.team_w_coverage * coverage
            - settings.team_w_redundancy * redundancy
            - settings.team_w_location * location_red
        )

        if score > best_score:
            best_score = score
            best = TeamPick(
                team_size=n,
                sme_ids=[c.sme_id for c in combo],
                team_score=round(score, 4),
                coverage_breadth=round(coverage, 4),
                redundancy=round(redundancy, 4),
                rationale_text=_render_rationale(
                    combo=combo,
                    covered_topic_ids=covered,
                    conf_topic_count=len(conf_topic_ids),
                    topic_name_by_id=topic_name_by_id,
                ),
                members=[
                    TeamMember(
                        sme_id=c.sme_id,
                        full_name=c.full_name,
                        team=c.team,
                        is_external=c.is_external,
                        individual_score=c.composite,
                        location_city=c.location_city,
                        covered_topics=sorted(
                            topic_name_by_id[tid]
                            for tid in (
                                member_topic_ids.get(UUID(c.sme_id), set()) & conf_topic_ids
                            )
                            if tid in topic_name_by_id
                        ),
                    )
                    for c in combo
                ],
            )

    return best


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def _redundancy(topic_sets: list[set[UUID]]) -> float:
    """Mean pairwise Jaccard between members' topic sets. 0 for n=1
    (no pairs); high values for highly-redundant teams."""
    if len(topic_sets) < 2:
        return 0.0
    pairs = list(combinations(topic_sets, 2))
    sims = []
    for a, b in pairs:
        if not a and not b:
            continue
        inter = len(a & b)
        union = len(a | b)
        sims.append(inter / union if union else 0.0)
    return sum(sims) / len(sims) if sims else 0.0


def _location_redundancy(sme_ids: list[UUID], sme_rows: dict[UUID, Sme], is_virtual: bool) -> float:
    """Fraction of pairs sharing the same city. Zero for virtual events
    (location is meaningless) or fewer than 2 members."""
    if is_virtual or len(sme_ids) < 2:
        return 0.0
    cities = [(sme_rows[sid].location_city or "").lower() for sid in sme_ids if sid in sme_rows]
    cities = [c for c in cities if c]
    if len(cities) < 2:
        return 0.0
    pair_count = len(list(combinations(cities, 2)))
    same_count = sum(1 for a, b in combinations(cities, 2) if a == b)
    return same_count / pair_count


def _render_rationale(
    *,
    combo: tuple[SmeBreakdown, ...],
    covered_topic_ids: set[UUID],
    conf_topic_count: int,
    topic_name_by_id: dict[UUID, str],
) -> str:
    """One-sentence templated rationale; no LLM."""
    if len(combo) == 1:
        c = combo[0]
        suffix = (
            f" — covers {len(covered_topic_ids)} of {conf_topic_count} conference topics"
            if conf_topic_count
            else ""
        )
        return f"{c.full_name} (team {c.team}, composite {c.composite:.2f}){suffix}."

    names = ", ".join(f"{c.full_name} ({c.team})" for c in combo)
    if not conf_topic_count:
        return f"Together: {names}."
    topic_names = sorted(
        topic_name_by_id[tid] for tid in covered_topic_ids if tid in topic_name_by_id
    )
    if topic_names:
        first_few = ", ".join(topic_names[:5])
        more = f" (+{len(topic_names) - 5} more)" if len(topic_names) > 5 else ""
        return (
            f"Together {names} cover {len(covered_topic_ids)} of "
            f"{conf_topic_count} conference topics: {first_few}{more}."
        )
    return f"Together {names} cover none of the conference topics yet (will improve as topics get linked)."


# ---------------------------------------------------------------------------
# DB index helpers
# ---------------------------------------------------------------------------
async def _conference_topic_ids(db: AsyncSession, conference_id: UUID) -> set[UUID]:
    rows = (
        await db.execute(
            select(ConferenceTopic.topic_id, Topic.is_active, Topic.pending_review)
            .join(Topic, Topic.id == ConferenceTopic.topic_id)
            .where(ConferenceTopic.conference_id == conference_id)
        )
    ).all()
    return {tid for tid, active, pending in rows if active and not pending}


async def _sme_topic_ids(db: AsyncSession, sme_ids: list[UUID]) -> dict[UUID, set[UUID]]:
    if not sme_ids:
        return {}
    rows = (
        await db.execute(
            select(SmeTopic.sme_id, SmeTopic.topic_id).where(SmeTopic.sme_id.in_(sme_ids))
        )
    ).all()
    out: dict[UUID, set[UUID]] = {sid: set() for sid in sme_ids}
    for sid, tid in rows:
        out.setdefault(sid, set()).add(tid)
    return out


async def _sme_rows(db: AsyncSession, sme_ids: list[UUID]) -> dict[UUID, Sme]:
    if not sme_ids:
        return {}
    rows = (await db.execute(select(Sme).where(Sme.id.in_(sme_ids)))).scalars().all()
    return {r.id: r for r in rows}


async def _topic_name_index(db: AsyncSession, topic_ids: set[UUID]) -> dict[UUID, str]:
    if not topic_ids:
        return {}
    rows = (
        await db.execute(select(Topic.id, Topic.name).where(Topic.id.in_(list(topic_ids))))
    ).all()
    return {tid: name for tid, name in rows}
