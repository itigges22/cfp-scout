"""The cron table and the enqueueable-task registry.

WHAT THIS DOES
    Maps a task name to its callable (``ENQUEUEABLE``), registers those by
    name at startup, and installs the recurring cron entries.

HOW IT CONNECTS
    Called by   app/lifespan.py and app/scheduler_standalone.py
    Fires       app/tasks.py
    Helpers     app/scheduler.py owns the APScheduler instance
    Tuning      settings.scheduler_timezone

WORTH KNOWING
    This is deliberately NOT part of app/scheduler.py, and the reason is
    mechanical rather than stylistic: it is the one module that imports
    app.tasks at module scope, and app.tasks (plus the services it calls)
    imports app.scheduler for enqueue_task. Merged into scheduler.py the
    import graph closes into a cycle three different ways. The file
    boundary IS the cycle break.

    Exactly one scheduler may run — see app/scheduler.py.
"""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.scheduler import register_task
from app.settings import get_settings
from app.tasks import (
    build_cfp_digest_task,
    enrich_and_match_task,
    heartbeat,
    parse_raw_page_task,
    poll_sources_due_for_crawl,
    rescore_stale_matches,
    run_discovery_task,
    run_fit_match_task,
)

log = structlog.get_logger("scout.jobs")


ENQUEUEABLE: dict[str, object] = {
    "enrich_and_match": enrich_and_match_task,
    "parse_raw_page": parse_raw_page_task,
    "run_fit_match": run_fit_match_task,
}


def register_tasks() -> None:
    """Make the enqueueable tasks reachable by name.

    Called at startup, before anything can queue work. Separate from
    :func:`register_jobs` because these are queued on demand by services and
    routers, not run on a timer.
    """
    for name, func in ENQUEUEABLE.items():
        register_task(name, func)
    log.info("scheduler.tasks_registered", count=len(ENQUEUEABLE))


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register the recurring (cron) schedule.

    Each ``add_job`` uses an explicit ``id=`` so re-runs are idempotent —
    if the job already exists in the jobstore (from a prior boot), it gets
    replaced rather than duplicated.

    What actually runs, and why:

      heartbeat        every 10 min — proves the scheduler is alive
      scrape_poll      every 15 min — sources due for a crawl
      rescore_stale    hourly       — conferences with no match at the
                                      current ALGORITHM_VERSION
      cfp_digest       daily 09:00
      discovery        per settings

    This list previously named two jobs that were never registered, one of
    which (``recompute_upcoming_matches``) did not exist as a function at
    all. A schedule that lies is worse than a short one: it is the first
    place someone looks to answer "why did nothing happen overnight".
    """


    scheduler.add_job(
        heartbeat,
        trigger="interval",
        minutes=10,
        id="heartbeat",
        replace_existing=True,
    )
    # Bringing conferences up to the current ALGORITHM_VERSION. Every read
    # path joins matches on that constant, so bumping it makes every stored
    # score invisible at once — blank list, empty dashboard, 404s from
    # /conferences/{id}/match. This is what makes the version bump
    # self-healing rather than something an operator has to notice.
    #
    # Hourly, not daily, because the blank window is user-visible. Cheap:
    # it selects only conferences missing a current-version row, so it is a
    # no-op once the corpus has caught up. An unconditional rescore would
    # re-run the LLM judge on everything, every time.
    scheduler.add_job(
        rescore_stale_matches,
        trigger="interval",
        hours=1,
        id="rescore_stale",
        replace_existing=True,
    )
    # Every 15 minutes, scan ``sources`` for rows whose
    # ``last_crawled_at`` is older than ``crawl_cadence`` and enqueue a
    # scrape each. Per-source ``politeness_delay_seconds`` enforces inside
    # the crawl itself.
    scheduler.add_job(
        poll_sources_due_for_crawl,
        trigger="interval",
        minutes=15,
        id="scrape_poll",
        replace_existing=True,
    )
    # Daily 09:00 (scheduler timezone, default UTC) CFP digest.
    # Builds the bell-badge notification. Idempotent within a day.
    scheduler.add_job(
        build_cfp_digest_task,
        trigger="cron",
        hour=9,
        minute=0,
        id="cfp_digest",
        replace_existing=True,
    )
    # Daily autonomous discovery (default 06:00 UTC). Searches
    # the web via the configured provider, fetches with Crawl4AI, and
    # runs every successful crawl through the extraction pipeline. No-op
    # when DISCOVERY_ENABLED=false.

    discovery_hour = int(getattr(get_settings(), "discovery_cron_hour_utc", 6))
    scheduler.add_job(
        run_discovery_task,
        trigger="cron",
        hour=discovery_hour,
        minute=0,
        id="discovery",
        replace_existing=True,
    )
    log.info("scheduler.jobs_registered", count=len(scheduler.get_jobs()))
