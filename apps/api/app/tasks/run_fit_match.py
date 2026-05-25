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
    """Process every non-quarantined conference inline with bounded
    concurrency.

    Previous version fanned each conference out as its OWN APScheduler
    job. With 583 conferences, that meant 583 jobs all firing in the
    event loop at once, each grabbing a DB session, and the SQLAlchemy
    pool (5 + 10 overflow = 15 max) exhausted in seconds → 564 timed
    out at QueuePool. The LLM semaphore couldn't help because the
    bottleneck was DB connections, not LLM calls.

    Now: one orchestrator task loops the conferences and runs them
    through an asyncio.Semaphore-bounded gather. Concurrency lives at
    the matcher-job level (default 4); each task acquires its own
    short-lived DB session inside _do_run_fit_match, returns it
    promptly, and the pool stays healthy. The LLM semaphore still
    applies inside each task for the actual LLM call.
    """
    import asyncio

    async with get_session_factory()() as session:
        rows = (
            await session.execute(select(Conference.id).where(Conference.status != "quarantined"))
        ).all()
    conf_ids = [str(cid) for (cid,) in rows]
    log.info("matcher.recompute_all.start", count=len(conf_ids))

    # Concurrency knob: keep below the DB pool ceiling (15) with headroom
    # for the rest of the app. 4 is safe; tune via the same setting that
    # gates LLM calls (llm_max_concurrent_calls) since both share an
    # operational story.
    from app.settings import get_settings

    cap = max(1, min(8, int(get_settings().llm_max_concurrent_calls)))
    sem = asyncio.Semaphore(cap)
    results = {"succeeded": 0, "failed": 0}

    async def _one(cid: str) -> None:
        async with sem:
            try:
                await _do_run_fit_match(conference_id=cid)
                results["succeeded"] += 1
            except Exception as exc:  # noqa: BLE001 — keep the loop going
                results["failed"] += 1
                log.warning(
                    "matcher.recompute_all.task_failed",
                    conference_id=cid,
                    error=str(exc)[:200],
                )

    # asyncio.gather schedules all tasks but the semaphore caps how many
    # actually proceed past `async with sem`. The rest park on the
    # semaphore without holding DB connections.
    await asyncio.gather(*(_one(cid) for cid in conf_ids))

    log.info(
        "matcher.recompute_all.done",
        total=len(conf_ids),
        succeeded=results["succeeded"],
        failed=results["failed"],
        concurrency_cap=cap,
    )
    return {
        "total": len(conf_ids),
        "succeeded": results["succeeded"],
        "failed": results["failed"],
        "concurrency_cap": cap,
    }


async def recompute_all_matches() -> dict[str, Any]:
    """APScheduler-callable. Fans out one ``run_fit_match_task`` per
    non-quarantined conference. Tracked as a single ingest_jobs row."""
    return await run_as_job("matcher_recompute_all", _do_recompute_all)
