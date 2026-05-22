"""Background scrape task (plan 14).

Two entry points:

  * :func:`scrape_source_task(source_id)` — runs the full crawl pipeline
    for one source. Used by ``POST /api/v1/sources/{id}/crawl-now`` and by
    the 15-minute cron.

  * :func:`poll_sources_due_for_crawl` — cron entry. Enumerates enabled
    sources whose ``last_crawled_at`` is older than ``crawl_cadence`` and
    enqueues a scrape for each.

Both are JSON-friendly (source_id passed as str) so APScheduler's persistent
jobstore can pickle the kwargs without a custom serializer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, text as sql_text

from app.db.models.entities import Source
from app.db.session import get_session_factory
from app.scheduler import enqueue_now
from app.services.scraper import crawl_source as run_crawl_source
from app.services.scraper.pipeline import SourceDisabledError, SourceNotFoundError
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.scrape")


async def _do_scrape(*, source_id: str) -> dict[str, Any]:
    """Inner crawl runner — opens its own DB session."""
    async with get_session_factory()() as session:
        try:
            result = await run_crawl_source(session, UUID(source_id))
        except (SourceNotFoundError, SourceDisabledError):
            await session.rollback()
            raise
        await session.commit()
    return result.to_stats()


async def scrape_source_task(*, source_id: str) -> dict[str, Any]:
    """APScheduler-callable. Wraps the crawl in :func:`run_as_job` so an
    ``app.ingest_jobs`` row tracks the run."""
    return await run_as_job(
        "scrape_source",
        _do_scrape,
        source_id=source_id,
        stats_extra={"source_id": source_id},
    )


async def _do_poll() -> dict[str, Any]:
    """Find sources due for crawl + enqueue one scrape per."""
    enqueued: list[str] = []
    async with get_session_factory()() as session:
        # "Due" = enabled AND (never crawled OR last_crawled_at older than cadence).
        # cadence is stored as text (e.g. "1 day"); cast to interval inline.
        # Note: cadence text is validated at the schema layer against a
        # small allowlist of `<int> <unit>` shapes, so the cast is safe.
        stmt = (
            select(Source)
            .where(Source.enabled.is_(True))
            .where(
                sql_text(
                    "last_crawled_at IS NULL "
                    "OR last_crawled_at < now() - cast(crawl_cadence AS interval)"
                )
            )
        )
        result = await session.execute(stmt)
        for source in result.scalars():
            job_id = f"scrape-{source.id}"
            enqueue_now(
                scrape_source_task,
                job_id=job_id,
                kwargs={"source_id": str(source.id)},
            )
            enqueued.append(str(source.id))
            log.info(
                "scrape.poll.enqueued",
                source_id=str(source.id),
                source_name=source.name,
            )
    return {"enqueued_source_count": len(enqueued), "source_ids": enqueued}


async def poll_sources_due_for_crawl() -> dict[str, Any]:
    """APScheduler-callable. Cron entry point — runs every 15 minutes via
    :func:`app.scheduler.register_jobs`."""
    return await run_as_job("scrape_poll", _do_poll)
