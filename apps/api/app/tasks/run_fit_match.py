"""Background matcher task (plan 17).

Two entry points:

  * :func:`run_fit_match_task(conference_id)` — score one conference.
    Enqueued by the extraction pipeline (when a new conference appears),
    by ``POST /api/v1/admin/matcher/run-now/{id}``, and by the bulk
    recompute below.

  * :func:`recompute_all_matches` — fan out a ``run_fit_match_task`` per
    non-quarantined conference. Triggered manually or after a messaging /
    pillar / SME roster change.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from app.db.models.entities import Conference
from app.db.session import get_session_factory
from app.scheduler import enqueue_now
from app.services.matcher import run_fit_match
from app.services.matcher.pipeline import (
    ConferenceNotFoundError,
    ConferenceQuarantinedError,
)
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.matcher")


async def _do_run_fit_match(*, conference_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        try:
            result = await run_fit_match(session, UUID(conference_id))
        except (ConferenceNotFoundError, ConferenceQuarantinedError):
            await session.rollback()
            raise
        await session.commit()
    return result.to_stats()


async def run_fit_match_task(*, conference_id: str) -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job`."""
    return await run_as_job(
        "run_fit_match",
        _do_run_fit_match,
        conference_id=conference_id,
        stats_extra={"conference_id": conference_id},
    )


async def _do_recompute_all() -> dict[str, Any]:
    enqueued: list[str] = []
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(Conference.id).where(Conference.status != "quarantined")
            )
        ).all()
    for (cid,) in rows:
        job_id = f"match-{cid}"
        enqueue_now(
            run_fit_match_task,
            job_id=job_id,
            kwargs={"conference_id": str(cid)},
        )
        enqueued.append(str(cid))
    log.info("matcher.recompute_all.enqueued", count=len(enqueued))
    return {"enqueued_count": len(enqueued), "conference_ids": enqueued}


async def recompute_all_matches() -> dict[str, Any]:
    """APScheduler-callable. Fans out one ``run_fit_match_task`` per
    non-quarantined conference. Tracked as a single ingest_jobs row."""
    return await run_as_job("matcher_recompute_all", _do_recompute_all)
