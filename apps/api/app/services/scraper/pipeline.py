"""End-to-end crawl pipeline for a single source (plan 14).

Entry point: :func:`crawl_source` — takes a ``source_id`` + a DB session,
returns a :class:`CrawlResult` with per-status counts. The caller (the
scheduler task or the admin "Crawl now" button) is responsible for opening
the session and committing.

Flow:
  1. Load + validate Source row (enabled? supported kind?)
  2. Build the SSRF-guarded client + politeness helpers
  3. Discover candidate URLs via ``discovery.discover_urls``
  4. For each URL: ``fetch.fetch_one`` (robots → rate-limit → conditional GET
     → dedupe → persist)
  5. Update ``sources.last_crawled_at``
  6. Return aggregated stats

This function never raises on per-URL errors — they're aggregated into
``CrawlResult.errors``. Top-level errors (source not found, discovery
endpoint unreachable) DO raise so the task runner records a failed
``ingest_jobs`` row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Source
from app.services.scraper.client import make_async_client
from app.services.scraper.discovery import discover_urls
from app.services.scraper.fetch import fetch_one
from app.services.scraper.politeness import RateLimiter, RobotsCache
from app.settings import get_settings

log = structlog.get_logger("scout.scraper.pipeline")


class SourceNotFoundError(LookupError):
    """Raised when ``crawl_source`` can't find the source row."""


class SourceDisabledError(RuntimeError):
    """Raised when the source row exists but ``enabled=false``."""


@dataclass(slots=True)
class CrawlResult:
    """Aggregated outcome of a crawl run for one source.

    Serializable via ``asdict`` so the task runner can drop it into
    ``ingest_jobs.stats``.
    """

    source_id: str
    source_name: str
    pages_discovered: int = 0
    pages_fetched: int = 0
    pages_deduped: int = 0
    pages_skipped_robots: int = 0
    pages_skipped_304: int = 0
    pages_js_blocked: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_stats(self) -> dict:
        return asdict(self)


async def crawl_source(db: AsyncSession, source_id: UUID) -> CrawlResult:
    """Run a full crawl for ``source_id`` and return aggregated stats."""
    source = await db.get(Source, source_id)
    if source is None:
        raise SourceNotFoundError(f"No source {source_id!s}")
    if not source.enabled:
        raise SourceDisabledError(
            f"Source {source.name!r} ({source.id}) is disabled."
        )

    bound = log.bind(source_id=str(source.id), source_name=source.name, kind=source.kind)
    bound.info("scraper.crawl.start", url=source.url)

    settings = get_settings()
    result = CrawlResult(source_id=str(source.id), source_name=source.name)

    robots = RobotsCache()
    rate_limit = RateLimiter()
    # Set per-host delay from the source's configured politeness.
    import urllib.parse

    host = urllib.parse.urlsplit(source.url).netloc
    rate_limit.set_delay(host, source.politeness_delay_seconds)

    async with make_async_client(user_agent=settings.scraper_user_agent) as client:
        try:
            candidate_urls = await discover_urls(
                kind=source.kind, url=source.url, client=client
            )
        except Exception as exc:  # noqa: BLE001 — discovery failure is a hard fail
            bound.error("scraper.discovery_failed", error=str(exc))
            raise

        result.pages_discovered = len(candidate_urls)
        bound.info("scraper.crawl.discovered", count=len(candidate_urls))

        # IDs of raw_pages we'll enqueue for plan-15 extraction after the
        # crawl finishes. Collect now, dispatch later — APScheduler add_job
        # is fast but doing it inside the per-URL await would slow the
        # loop without benefit.
        new_raw_page_ids: list[str] = []

        for url in candidate_urls:
            outcome = await fetch_one(
                db=db,
                source_id=source.id,
                url=url,
                user_agent=settings.scraper_user_agent,
                client=client,
                robots=robots,
                rate_limit=rate_limit,
            )
            if outcome.status == "fetched":
                result.pages_fetched += 1
                if outcome.raw_page_id is not None:
                    new_raw_page_ids.append(str(outcome.raw_page_id))
            elif outcome.status == "deduped":
                result.pages_deduped += 1
            elif outcome.status == "skipped_robots":
                result.pages_skipped_robots += 1
            elif outcome.status == "skipped_304":
                result.pages_skipped_304 += 1
            elif outcome.status == "js_blocked":
                result.pages_js_blocked += 1
                # JS-blocked pages still got persisted; we explicitly skip
                # extraction since the body is unlikely to yield anything
                # useful to the LLM.
            elif outcome.status == "error":
                result.errors.append(
                    {
                        "url": outcome.url,
                        "http_status": outcome.http_status,
                        "error": outcome.error,
                    }
                )

    source.last_crawled_at = datetime.now(tz=timezone.utc)
    await db.flush()

    # Enqueue plan-15 extraction for each newly-fetched raw_page. Local
    # import keeps the scraper package free of a circular dep on the tasks
    # package (which itself imports the scheduler).
    if new_raw_page_ids:
        from app.scheduler import enqueue_now
        from app.tasks.parse_raw_page import parse_raw_page_task

        for rp_id in new_raw_page_ids:
            enqueue_now(
                parse_raw_page_task,
                job_id=f"parse-{rp_id}",
                kwargs={"raw_page_id": rp_id},
            )
        bound.info("scraper.crawl.parse_enqueued", count=len(new_raw_page_ids))

    bound.info("scraper.crawl.done", **result.to_stats() | {"errors": len(result.errors)})
    return result
