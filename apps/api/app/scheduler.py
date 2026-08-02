"""The scheduler: the task registry, the cron table, and its lifecycle.

WHAT THIS DOES
    Owns the APScheduler instance, the registry that maps a task name to
    its callable, ``enqueue_task`` for firing one now, and
    ``register_jobs`` which installs the cron entries at startup.

HOW IT CONNECTS
    Called by   app/lifespan.py (embedded mode) and
                app/scheduler_standalone.py (its own process)
    Fires       app/tasks.py
    Tuning      settings.scheduler_mode, settings.scheduler_timezone

WORTH KNOWING
    ``jobs.py`` existed to hold ``register_jobs`` and was described as the
    one module allowed to import app.tasks — a rule about imports, kept by
    putting it in a file that only the scheduler called. The rule is the
    same now and the code is where it is used.

    Exactly one scheduler may run. In embedded mode a multi-replica API
    would start one per replica, which is why the standalone deployment
    exists and why ``scheduler_mode`` is not cosmetic.

    APScheduler coalesces missed fires and runs one instance per job id,
    so enqueuing the same id twice collapses into one run.
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


# ==========================================================================
# scheduler.py
# ==========================================================================


_scheduler: AsyncIOScheduler | None = None


_LEADER_LOCK_KEY = 0x5C0_5CCD  # ad-hoc "scout-scheduler" tag


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
            f"DATABASE_URL must use the ``postgresql+asyncpg://`` scheme; got {async_url!r}"
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


def start_scheduler() -> bool:
    """Start the singleton scheduler + register cron jobs in the leader worker.

    Returns True if this process became the leader and is now firing jobs,
    False if another process holds the lock.

    The return value matters for ``scheduler_standalone``: that process
    exists ONLY to be the leader, so "I am passive" is a failure there,
    even though it is the normal outcome for an API worker.
    """
    if not _try_acquire_leader_lock():
        log.info("scheduler.passive", reason="leader_lock_held_by_other_worker")
        return False

    scheduler = get_scheduler()
    if scheduler.running:
        log.warning("scheduler.already_running")
        return True
    scheduler.start()
    log.info(
        "scheduler.started",
        timezone=str(scheduler.timezone),
        executors=list(scheduler._executors.keys()),
        jobstores=list(scheduler._jobstores.keys()),
    )
    return True


def start_scheduler_paused() -> None:
    """Start the scheduler paused: jobstore attached, nothing fires here.

    For SCHEDULER_MODE=disabled processes (HPA-scaled api pods on
    OpenShift). APScheduler's ``add_job`` on a never-started scheduler
    only buffers jobs in the process-local ``_pending_jobs`` list — they
    never reach the shared Postgres jobstore, so every admin "run now"
    endpoint (``enqueue_now``) silently no-ops on those pods while the
    standalone scheduler sees nothing. Starting paused flushes adds
    straight to the jobstore (the standalone scheduler picks them up at
    its next wakeup) without this process ever executing a job.

    No leader lock: a paused scheduler fires nothing, so every worker
    can safely attach.
    """
    scheduler = get_scheduler()
    if scheduler.running:
        log.warning("scheduler.already_running")
        return
    scheduler.start(paused=True)
    log.info(
        "scheduler.started_paused",
        reason="jobstore_write_path_for_enqueue_now",
        jobstores=list(scheduler._jobstores.keys()),
    )


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


_TASKS: dict[str, Any] = {}


def register_task(name: str, func: Any) -> None:
    """Make ``name`` enqueueable. Called once per task at startup."""
    _TASKS[name] = func


def enqueue_task(
    name: str,
    *,
    job_id: str | None = None,
    kwargs: dict[str, Any] | None = None,
) -> str:
    """Queue a registered task by name.

    The trade against importing the function directly: a typo here fails at
    call time rather than import time. ``test_task_registry.py`` closes that
    gap by asserting every name used anywhere in app/services is registered.
    """
    func = _TASKS.get(name)
    if func is None:
        raise KeyError(
            f"No task registered under {name!r}. Known: {sorted(_TASKS)}. "
            f"Tasks are registered in app/scheduler.py at startup."
        )
    return enqueue_now(func, job_id=job_id, kwargs=kwargs)


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
        replace_existing=bool(job_id),
        # None = run no matter how late. The standalone scheduler only
        # discovers externally-enqueued jobs at its next wakeup — which
        # was ~10 minutes out on a quiet jobstore, past the old 300s
        # grace, so APScheduler silently DISCARDED the job and the
        # operator watched "queued" forever. Late beats never for every
        # caller of this helper.
        misfire_grace_time=None,
    )
    return job.id
