"""/api/v1/admin/matcher — manually drive the matcher (plan 17).

Endpoints:

  * ``POST /admin/matcher/run-now/{conference_id}``
        Run the matcher synchronously and return the :class:`MatchResult`
        payload. Useful for verification + rapid threshold tuning.

  * ``POST /admin/matcher/run-now-async/{conference_id}``
        Enqueue the matcher via the scheduler; returns the queued job_id.

  * ``POST /admin/matcher/recompute-all``
        Enqueue one matcher run per non-quarantined conference. Used after
        messaging changes, pillar edits, SME roster updates, or an
        ``algorithm_version`` bump.

  * ``GET /admin/matcher/matches/recent?limit=50``
        Latest matches rows for inspection — handy in tandem with the
        algorithm version + threshold tweaks.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.db.models.matching import Match
from app.db.session import DbSession
from app.scheduler import enqueue_now
from app.services.matcher import ALGORITHM_VERSION, run_fit_match
from app.services.matcher.sme_narrative import compute_narratives_for_top_smes
from app.services.matcher.teams import recommend_teams
from app.tasks.compute_sme_fit_narrative import (
    compute_sme_fit_narrative_task,
    recompute_narratives_for_all,
)
from app.tasks.recommend_teams import recommend_teams_task
from app.tasks.run_fit_match import recompute_all_matches, run_fit_match_task

log = structlog.get_logger("scout.api.admin_matcher")
router = APIRouter(prefix="/api/v1/admin/matcher", tags=["admin.matcher"])


@router.post("/run-now/{conference_id}")
async def run_now(db: DbSession, conference_id: UUID) -> dict:
    """Run the matcher synchronously and return the MatchResult."""
    log.info("admin.matcher.run_now", conference_id=str(conference_id))
    result = await run_fit_match(db, conference_id)
    await db.commit()
    return result.to_stats()


@router.post("/run-now-async/{conference_id}", status_code=status.HTTP_202_ACCEPTED)
async def run_now_async(conference_id: UUID) -> dict:
    job_id = enqueue_now(
        run_fit_match_task,
        job_id=f"match-{conference_id}",
        kwargs={"conference_id": str(conference_id)},
    )
    log.info("admin.matcher.run_enqueued", conference_id=str(conference_id), job_id=job_id)
    return {"queued_job_id": job_id, "conference_id": str(conference_id)}


@router.post("/recompute-all", status_code=status.HTTP_202_ACCEPTED)
async def recompute_all() -> dict:
    """Enqueue one matcher run per non-quarantined conference."""
    job_id = enqueue_now(
        recompute_all_matches,
        job_id="matcher_recompute_all_manual",
    )
    log.info("admin.matcher.recompute_all", job_id=job_id)
    return {"queued_job_id": job_id, "algorithm_version": ALGORITHM_VERSION}


@router.post("/narratives/regenerate/{conference_id}")
async def regenerate_narratives(db: DbSession, conference_id: UUID) -> dict:
    """Wipe + recompute the SME-fit narratives for this conference.

    Sync run (LLM-bound; typically <2s with K=3). Use the async variant
    below for very long-running cases.
    """
    log.info("admin.matcher.regenerate_narratives", conference_id=str(conference_id))
    result = await compute_narratives_for_top_smes(db, conference_id, force=True)
    await db.commit()
    return result.to_stats() | {
        "narratives": [
            {
                "sme_id": n.sme_id,
                "sme_name": n.sme_name,
                "composite": n.composite,
                "narrative": n.narrative,
                "cached": n.cached,
            }
            for n in result.narratives
        ],
    }


@router.post(
    "/narratives/regenerate-async/{conference_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_narratives_async(conference_id: UUID) -> dict:
    job_id = enqueue_now(
        compute_sme_fit_narrative_task,
        job_id=f"narrative-{conference_id}",
        kwargs={"conference_id": str(conference_id), "force": True},
    )
    return {"queued_job_id": job_id, "conference_id": str(conference_id)}


@router.post("/narratives/recompute-all", status_code=status.HTTP_202_ACCEPTED)
async def recompute_all_narratives() -> dict:
    job_id = enqueue_now(
        recompute_narratives_for_all,
        job_id="narrative_recompute_all_manual",
    )
    return {"queued_job_id": job_id, "algorithm_version": ALGORITHM_VERSION}


@router.get("/matches/recent")
async def recent_matches(db: DbSession, limit: int = Query(default=50, ge=1, le=500)) -> dict:
    rows = (
        (await db.execute(select(Match).order_by(Match.computed_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "limit": limit,
        "matches": [
            {
                "id": str(m.id),
                "conference_id": str(m.conference_id),
                "algorithm_version": m.algorithm_version,
                "messaging_score": round(float(m.messaging_score), 4),
                "pillar_score": round(float(m.pillar_score), 4),
                "sme_score": round(float(m.sme_score), 4),
                "overall_score": round(float(m.overall_score), 4),
                "recommended_sme_ids": [str(s) for s in m.recommended_sme_ids],
                "rationale_text_preview": (m.rationale_text or "")[:200],
                "computed_at": m.computed_at.isoformat() if m.computed_at else None,
            }
            for m in rows
        ],
    }


@router.post("/teams-now/{conference_id}")
async def teams_now(db: DbSession, conference_id: UUID) -> dict:
    """Run plan-32 team recommendations synchronously. Returns the three
    team picks (size 1/2/3) plus the candidate count."""
    log.info("admin.matcher.teams_now", conference_id=str(conference_id))
    result = await recommend_teams(db, conference_id)
    await db.commit()
    return result.to_dict()


@router.post("/teams-now-async/{conference_id}", status_code=status.HTTP_202_ACCEPTED)
async def teams_now_async(conference_id: UUID) -> dict:
    job_id = enqueue_now(
        recommend_teams_task,
        job_id=f"teams-{conference_id}",
        kwargs={"conference_id": str(conference_id)},
    )
    return {"queued_job_id": job_id, "conference_id": str(conference_id)}


@router.post("/link-past-conference-series")
async def link_past_conference_series(
    db: DbSession,
    link_threshold: float = Query(default=0.82, ge=0.5, le=1.0),
    review_threshold: float = Query(default=0.65, ge=0.5, le=1.0),
) -> dict:
    """Fuzzy-match unlinked past_conferences to conference_series by name.

    Uses pg_trgm similarity (same as the conference orphan linker).
    Rows >= link_threshold get series_id set. Rows in [review_threshold,
    link_threshold) are logged as needs_review without writing.
    Returns: {linked, skipped, needs_review}.
    """
    from app.services.series.crud import link_past_conference_series_orphans

    log.info(
        "admin.matcher.link_past_conf_series",
        link_threshold=link_threshold,
        review_threshold=review_threshold,
    )
    result = await link_past_conference_series_orphans(
        db,
        link_threshold=link_threshold,
        review_threshold=review_threshold,
    )
    await db.commit()
    return result.to_dict()
