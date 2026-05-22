"""Matcher orchestrator (plan 17).

Calls the three stages in order, computes the weighted overall, generates
rationale, persists ``app.matches``. Returns a typed ``MatchResult`` for
the caller (task runner / admin endpoint) to surface.

Status assignment uses the same conferences.status field as the extraction
pipeline. The matcher upgrades/downgrades a conference based on the gate
exits:

  Stage A below ``MATCH_M_GATE``    → ``low_messaging_fit``
  Stage B below ``MATCH_P_GATE``    → ``needs_review_pillar``
  Stage C top SME < ``MATCH_S_GATE``→ ``needs_sme_review``
  Otherwise (all gates passed)      → ``approved``

Note: the extraction pipeline writes ``discovered`` / ``needs_review`` /
``quarantined`` based on extraction confidence. The matcher takes over
once a conference exists; ``quarantined`` rows are skipped entirely (the
graph loader and conference list already filter them).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference
from app.db.models.matching import Match
from app.services.matcher._scoring import clamp01
from app.services.matcher.messaging import (
    MessagingStageResult,
    stage_a_messaging_fit,
)
from app.services.matcher.pillars import (
    PillarStageResult,
    stage_b_pillar_alignment,
)
from app.services.matcher.rationale import generate_rationale
from app.services.matcher.smes import SmeStageResult, stage_c_sme_match
from app.settings import get_settings

log = structlog.get_logger("scout.matcher.pipeline")

# Bump this string whenever the matcher's behavior changes in a way that
# would produce different scores from the same inputs. The bump triggers
# bulk recompute (plan 17 + plan 25). Format: <semver-ish>.
ALGORITHM_VERSION = "matcher.v1.0"


class ConferenceNotFoundError(LookupError):
    pass


class ConferenceQuarantinedError(RuntimeError):
    """Quarantined conferences are skipped by the matcher — they're
    inert. Surfaced as an explicit error so the task runner can record it
    cleanly in ingest_jobs.error_text instead of silently exiting."""


@dataclass(slots=True)
class MatchResult:
    """Returned by :func:`run_fit_match`. Mirrors what's persisted in
    ``app.matches`` plus a few diagnostic extras."""

    conference_id: str
    conference_name: str
    algorithm_version: str
    status: str  # what the matcher set conferences.status to

    messaging_score: float
    pillar_score: float
    sme_score: float
    overall_score: float

    matched_pillar_name: str | None = None
    recommended_sme_ids: list[str] = field(default_factory=list)
    rationale_text: str = ""

    # Diagnostic; not persisted to matches table.
    n_messaging_pairs: int = 0
    per_pillar: list[dict] = field(default_factory=list)
    rationale_prompt_version: str = ""

    def to_stats(self) -> dict:
        return asdict(self)


async def run_fit_match(db: AsyncSession, conference_id: UUID) -> MatchResult:
    """Full matcher pipeline for one conference."""
    settings = get_settings()

    conference = await db.get(Conference, conference_id)
    if conference is None:
        raise ConferenceNotFoundError(f"No conference {conference_id!s}")
    if conference.status == "quarantined":
        raise ConferenceQuarantinedError(
            f"Conference {conference_id!s} is quarantined; matcher refuses to score it."
        )

    bound = log.bind(
        conference_id=str(conference.id),
        conference_name=conference.name,
        algorithm_version=ALGORITHM_VERSION,
    )
    bound.info("matcher.run.start")

    # ---- Stage A: messaging -----------------------------------------
    ms: MessagingStageResult = await stage_a_messaging_fit(db, conference.id)

    # ---- Stage B: pillars -------------------------------------------
    pl: PillarStageResult = await stage_b_pillar_alignment(db, conference.id)

    # ---- Stage C: SMEs ----------------------------------------------
    sm: SmeStageResult = await stage_c_sme_match(db, conference.id, gate=settings.match_s_gate)

    # ---- Overall + status -------------------------------------------
    overall = clamp01(
        settings.match_w_messaging * ms.score
        + settings.match_w_pillar * pl.score
        + settings.match_w_sme * sm.score
    )

    status = _choose_status(
        ms_score=ms.score,
        pl_score=pl.score,
        sm_score=sm.score,
        settings=settings,
    )

    # ---- Rationale ---------------------------------------------------
    rationale = await generate_rationale(
        db=db,
        conference_name=conference.name,
        messaging_snippets=ms.snippets,
        matched_pillar_name=pl.matched_pillar_name,
        sme_recs=sm.recommendations,
    )

    # ---- Persist ----------------------------------------------------
    recommended_sme_uuids = [UUID(r.sme_id) for r in sm.recommendations]

    # One row per (conference, algorithm_version). Re-run with the same
    # algorithm_version replaces the previous row's scores via UPDATE so
    # the matches table doesn't grow unbounded with reruns.
    existing = (
        await db.execute(
            select(Match)
            .where(Match.conference_id == conference.id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
        )
    ).scalar_one_or_none()
    now = datetime.now(tz=UTC)

    if existing is None:
        match = Match(
            conference_id=conference.id,
            messaging_score=ms.score,
            pillar_score=pl.score,
            sme_score=sm.score,
            overall_score=overall,
            recommended_sme_ids=recommended_sme_uuids,
            rationale_text=rationale or "",
            algorithm_version=ALGORITHM_VERSION,
            computed_at=now,
        )
        db.add(match)
    else:
        existing.messaging_score = ms.score
        existing.pillar_score = pl.score
        existing.sme_score = sm.score
        existing.overall_score = overall
        existing.recommended_sme_ids = recommended_sme_uuids
        existing.rationale_text = rationale or ""
        existing.computed_at = now
        match = existing

    # Update conferences.status (only when the matcher's verdict moves it
    # OUT of the extraction-set 'discovered'/'needs_review' states; we
    # don't clobber 'quarantined' from above).
    conference.status = status
    await db.flush()

    # Enqueue plan-19 narratives for the top-K SMEs of this conference.
    # Idempotent (plan 19 checks existing matches.sme_fit_narratives entries
    # before each LLM call) so retries are cheap. Local import avoids a
    # circular dep with the tasks package.
    if status != "quarantined" and sm.recommendations:
        from app.scheduler import enqueue_now
        from app.tasks.compute_sme_fit_narrative import (
            compute_sme_fit_narrative_task,
        )

        enqueue_now(
            compute_sme_fit_narrative_task,
            job_id=f"narrative-{conference.id}",
            kwargs={"conference_id": str(conference.id), "force": False},
        )

        # Plan 32: also enqueue multi-SME team recs (pure algorithmic; no
        # LLM cost). Picks complementary teams of size 1/2/3.
        from app.tasks.recommend_teams import recommend_teams_task

        enqueue_now(
            recommend_teams_task,
            job_id=f"teams-{conference.id}",
            kwargs={"conference_id": str(conference.id)},
        )

    bound.info(
        "matcher.run.done",
        messaging_score=round(ms.score, 4),
        pillar_score=round(pl.score, 4),
        sme_score=round(sm.score, 4),
        overall=round(overall, 4),
        status=status,
        rec_sme_count=len(sm.recommendations),
    )

    return MatchResult(
        conference_id=str(conference.id),
        conference_name=conference.name,
        algorithm_version=ALGORITHM_VERSION,
        status=status,
        messaging_score=round(ms.score, 4),
        pillar_score=round(pl.score, 4),
        sme_score=round(sm.score, 4),
        overall_score=round(overall, 4),
        matched_pillar_name=pl.matched_pillar_name,
        recommended_sme_ids=[r.sme_id for r in sm.recommendations],
        rationale_text=rationale or "",
        n_messaging_pairs=ms.n_compared,
        per_pillar=[asdict(h) for h in pl.per_pillar],
        rationale_prompt_version="rationale.match.v1",
    )


def _choose_status(
    *,
    ms_score: float,
    pl_score: float,
    sm_score: float,
    settings,
) -> str:
    """Plan 17 gate logic. Order matters — the first failing gate wins
    the status so admins see the earliest reason in the queue.
    """
    if ms_score < settings.match_m_gate:
        return "low_messaging_fit"
    if pl_score < settings.match_p_gate:
        return "needs_review_pillar"
    if sm_score < settings.match_s_gate:
        return "needs_sme_review"
    return "approved"
