"""Shared scaffolding for background tasks (plan 13).

Every task gets:
  * a fresh ``AsyncSession`` (no FastAPI request context to inherit from)
  * an ``app.ingest_jobs`` row created at start + closed on finish, so
    successes and failures are queryable from ``/admin/jobs/runs``
  * structlog binding of ``job_kind`` + ``job_id`` so log entries from a
    given run are easy to grep

Usage:
    from app.tasks._runner import run_as_job

    async def do_the_thing(...):
        ...

    async def my_task_entry():
        return await run_as_job("my.task", do_the_thing, ...)
"""

from __future__ import annotations

import time
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update

from app.db.models.ops import IngestJob
from app.db.session import get_session_factory

log = structlog.get_logger("scout.tasks")


async def run_as_job(
    kind: str,
    coro_factory: Callable[..., Awaitable[Any]],
    *,
    stats_extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute ``coro_factory(**kwargs)`` while tracking a row in
    ``app.ingest_jobs``.

    Returns a small dict describing the run: ``{ingest_job_id, status,
    duration_ms, stats}``. Exceptions are caught + recorded on the row +
    re-raised so the scheduler logs ``Job ... raised`` (and so callers in
    tests still see the error).
    """
    job_id = uuid.uuid4()
    bound = log.bind(job_kind=kind, ingest_job_id=str(job_id))
    bound.info("task.started")
    t0 = time.perf_counter()

    started_at = datetime.now(tz=UTC)
    stats_extra = stats_extra or {}

    # Open a session purely to create the tracking row. The actual work
    # opens its own session inside ``coro_factory`` (so a long task doesn't
    # hold a transaction open while it does CPU-heavy work).
    async with get_session_factory()() as session:
        row = IngestJob(
            id=job_id,
            kind=kind,
            status="running",
            started_at=started_at,
            stats=stats_extra,
        )
        session.add(row)
        await session.commit()

    try:
        result = await coro_factory(**kwargs)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        bound.error("task.failed", error=str(exc), duration_ms=duration_ms)
        async with get_session_factory()() as session:
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(
                    status="failed",
                    finished_at=datetime.now(tz=UTC),
                    error_text=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                    stats={**stats_extra, "duration_ms": duration_ms},
                )
            )
            await session.commit()
        raise

    duration_ms = int((time.perf_counter() - t0) * 1000)
    final_stats: dict[str, Any] = {**stats_extra, "duration_ms": duration_ms}
    if isinstance(result, dict):
        final_stats.update(result)

    async with get_session_factory()() as session:
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(
                status="complete",
                finished_at=datetime.now(tz=UTC),
                stats=final_stats,
            )
        )
        await session.commit()

    bound.info("task.completed", duration_ms=duration_ms, stats=final_stats)
    return {
        "ingest_job_id": str(job_id),
        "status": "complete",
        "duration_ms": duration_ms,
        "stats": final_stats,
    }
