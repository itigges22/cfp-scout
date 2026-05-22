"""In-process APScheduler (plan 13).

Why in-process:
  * Single user = single host. No distributed queue needed.
  * Postgres jobstore (``jobs.apscheduler_jobs``) survives ``make down/up``,
    so scheduled and queued work isn't lost on restarts.
  * One fewer container to maintain.
  * Cron + ad-hoc jobs unified in one library.
  * AsyncIOExecutor runs alongside FastAPI's event loop with no extra threads.

The scheduler is exposed as a module-level singleton via :func:`get_scheduler`.
:func:`start_scheduler` / :func:`stop_scheduler` are invoked from
``app/lifespan.py``. After start, ``register_jobs`` materialises the cron
schedule.

Adding a task:
  1. Implement the async function under ``app/tasks/`` accepting only
     JSON-serialisable kwargs (APScheduler serialises kwargs for the
     persistent jobstore).
  2. Register it in :func:`register_jobs` for cron, or enqueue ad-hoc via
     ``get_scheduler().add_job(func, 'date', ...)``.

Idempotency:
  Tasks are written so re-running with the same arguments is safe (e.g.
  ``embed_owner`` deletes prior chunks before inserting). APScheduler's
  ``max_instances=1`` + ``coalesce=True`` defaults below serialise concurrent
  fires with the same job-id.
"""

from __future__ import annotations

from typing import Any

import psycopg
import structlog
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.settings import get_settings

log = structlog.get_logger("scout.scheduler")

_scheduler: AsyncIOScheduler | None = None

# Leader-election lock key. Picked once + frozen so every worker process
# competes for the same advisory slot. Value is arbitrary as long as it's
# stable and doesn't collide with Postgres' own usage (which only takes
# user-supplied keys we provide here).
_LEADER_LOCK_KEY = 0x5C0_5CCD  # ad-hoc "scout-scheduler" tag

# Holds the psycopg connection that owns the advisory lock for this process.
# We keep the connection open for the lifetime of the api worker so the lock
# stays acquired. ``stop_scheduler`` closes it on shutdown.
_leader_conn: psycopg.Connection | None = None


def _build_sync_dsn() -> str:
    """Sync DSN for APScheduler's SQLAlchemyJobStore.

    APScheduler 3.x's SQLAlchemyJobStore is synchronous. The rest of the app
    rides asyncpg, but the jobstore needs a sync driver — we pin psycopg
    (v3) in pyproject and use the ``postgresql+psycopg`` scheme.

    Built from the same ``app`` role credentials as ``database_url``: we
    rewrite the scheme + driver but keep the user/host/db.
    """
    settings = get_settings()
    async_url = settings.database_url
    # Replace ``postgresql+asyncpg://`` with ``postgresql+psycopg://``.
    # str.replace is fine — the substring is unambiguous (no other ``+asyncpg``
    # would appear in a Postgres URL).
    sync_url = async_url.replace("+asyncpg://", "+psycopg://", 1)
    if sync_url == async_url:
        # database_url didn't use ``+asyncpg`` — caller passed a non-standard
        # form. Fail loud rather than silently using the wrong driver.
        raise RuntimeError(
            "DATABASE_URL must use the ``postgresql+asyncpg://`` scheme; "
            f"got {async_url!r}"
        )
    return sync_url


def _build_scheduler() -> AsyncIOScheduler:
    """Construct the scheduler. Called once per process from
    :func:`get_scheduler`.

    Jobstore config:
      * ``tablename='apscheduler_jobs'`` (default)
      * ``tableschema='jobs'`` — keeps APScheduler's table out of the ``app``
        schema where the OLTP tables live
      * Pickled job-state lands in a bytea column; APScheduler picks the
        protocol automatically.
    """
    settings = get_settings()

    jobstore = SQLAlchemyJobStore(
        url=_build_sync_dsn(),
        tableschema="jobs",
    )

    return AsyncIOScheduler(
        jobstores={"default": jobstore},
        executors={"default": AsyncIOExecutor()},
        job_defaults={
            # If a job is queued but the scheduler missed multiple fires
            # (e.g. the api was down), collapse them into a single run.
            "coalesce": True,
            # Prevent two copies of the same job from running concurrently —
            # e.g. two ``embed_owner`` calls for the same owner_id serialise.
            "max_instances": 1,
            # Allow a job that's late by up to 5 minutes to still run.
            # Older than that = skipped (a stale embed of a now-deleted entity
            # would be wasteful).
            "misfire_grace_time": 300,
        },
        timezone=settings.scheduler_timezone,
    )


def get_scheduler() -> AsyncIOScheduler:
    """Module-level singleton. Builds the scheduler on first access.

    Avoid calling at import time — :func:`get_settings` reads the env, which
    is wired up at app boot.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = _build_scheduler()
    return _scheduler


def _try_acquire_leader_lock() -> bool:
    """Best-effort Postgres advisory lock so exactly one api worker hosts the
    scheduler.

    Uvicorn's ``--workers N`` spawns N independent Python processes; without
    coordination every worker would start its own scheduler against the same
    Postgres jobstore and they'd race to fire each cron job. ``pg_try_advisory_lock``
    is non-blocking — workers that don't win the lock skip scheduler startup
    entirely.

    The connection holding the lock stays open for the process lifetime so the
    lock isn't released by Postgres' session-end logic. ``stop_scheduler``
    closes it on app shutdown.
    """
    global _leader_conn
    sync_dsn = _build_sync_dsn()
    # SQLAlchemy URL form is ``postgresql+psycopg://``; psycopg.connect wants
    # the bare ``postgresql://`` form.
    raw_dsn = sync_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    conn = psycopg.connect(raw_dsn, autocommit=True)
    try:
        cur = conn.execute("SELECT pg_try_advisory_lock(%s)", (_LEADER_LOCK_KEY,))
        row = cur.fetchone()
    except Exception:
        conn.close()
        raise
    if row is None or not row[0]:
        conn.close()
        return False
    _leader_conn = conn
    return True


def start_scheduler() -> None:
    """Start the singleton scheduler + register cron jobs in the leader worker.

    Safe to call once per process. Workers that don't win the leader lock
    log ``scheduler.passive`` and return — they handle API traffic but don't
    fire jobs.
    """
    if not _try_acquire_leader_lock():
        log.info("scheduler.passive", reason="leader_lock_held_by_other_worker")
        return

    scheduler = get_scheduler()
    if scheduler.running:
        log.warning("scheduler.already_running")
        return
    scheduler.start()
    log.info(
        "scheduler.started",
        timezone=str(scheduler.timezone),
        executors=list(scheduler._executors.keys()),
        jobstores=list(scheduler._jobstores.keys()),
    )
    register_jobs(scheduler)


def stop_scheduler() -> None:
    """Stop the scheduler. Idempotent."""
    global _scheduler, _leader_conn
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        log.info("scheduler.stopped")
    _scheduler = None
    # Release the advisory lock so a restarted worker can re-acquire.
    if _leader_conn is not None:
        try:
            _leader_conn.close()  # closing the session releases the lock
        except Exception:
            pass
        _leader_conn = None


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register the recurring (cron) schedule.

    Each ``add_job`` uses an explicit ``id=`` so re-runs are idempotent —
    if the job already exists in the jobstore (from a prior boot), it gets
    replaced rather than duplicated.

    Real implementations live in :mod:`app.tasks`. Tasks land plan-by-plan:
      * 13 (this plan): heartbeat — sanity check that the scheduler is alive
      * 14: ``poll_sources_due_for_crawl`` — every 15 min
      * 17: ``recompute_upcoming_matches`` — daily 04:00
      * 23: ``link_conference_series`` — weekly Mon 02:00
      * 24: ``build_cfp_digest`` — daily 09:00
      * 25: ``run_decay_pass`` — daily 03:00

    Plans 14-25 will extend this function; we don't pre-register stubs because
    AsyncIOScheduler eagerly imports the target function and we'd rather not
    ship broken imports.
    """
    from app.tasks.heartbeat import heartbeat
    from app.tasks.scrape_source import poll_sources_due_for_crawl

    scheduler.add_job(
        heartbeat,
        trigger="interval",
        minutes=10,
        id="heartbeat",
        replace_existing=True,
    )
    # Plan 14: every 15 minutes, scan ``sources`` for rows whose
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
    log.info("scheduler.jobs_registered", count=len(scheduler.get_jobs()))


def enqueue_now(
    func: Any,
    *,
    job_id: str | None = None,
    kwargs: dict[str, Any] | None = None,
) -> str:
    """Convenience helper used by API services to enqueue ad-hoc work.

    Wraps ``scheduler.add_job(func, 'date', run_date=None)`` which runs ASAP.
    Returns the resulting job id (auto-generated if ``job_id`` is None).

    With APScheduler's ``max_instances=1`` default, passing an explicit
    ``job_id`` per-entity (e.g. ``f"embed-audience-{owner_id}"``) means
    duplicate enqueues for the same target collapse into one — useful for
    de-bouncing rapid successive edits.
    """
    scheduler = get_scheduler()
    job = scheduler.add_job(
        func,
        trigger="date",  # run immediately
        kwargs=kwargs or {},
        id=job_id,
        replace_existing=True if job_id else False,
        misfire_grace_time=300,
    )
    return job.id
