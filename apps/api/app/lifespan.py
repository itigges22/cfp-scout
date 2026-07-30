"""Startup and shutdown, in the order that matters.

WHAT THIS DOES
    FastAPI runs this context manager once per process: everything before
    ``yield`` at boot, everything after on shutdown. The sequence is
    load-bearing, not cosmetic.

      1. Probe Postgres with SELECT 1. A failure re-raises so uvicorn exits
         non-zero and the container restarts, rather than serving 500s.
      2. Load runtime setting overrides from the database and clear the
         settings cache. After the probe, because it reads a table.
      3. Start the background loop that keeps those overrides fresh, so a
         key rotated on one replica reaches this one.
      4. Register the enqueueable tasks by name, BEFORE the mode branch —
         every replica queues work even when it runs no scheduler.
      5. Start the scheduler according to SCHEDULER_MODE.

    Shutdown reverses it: stop the refresh loop, stop the scheduler, dispose
    the database engine.

HOW IT CONNECTS
    Called by   app/main.py, passed as FastAPI(lifespan=...)
    Reads       Postgres (connectivity probe, app.app_setting_overrides)
    Helpers     app/db/session.py, app/scheduler.py, app/scheduler.py,
                services/settings_store/settings_store.py, services/settings_store/settings_store.py
    Tuning      settings.scheduler_mode, settings.settings_refresh_seconds

WORTH KNOWING
    PROCESS_START_TIME is set here and read by the /diagnostics uptime panel.
    A scheduler failure is logged rather than raised — the API stays up and
    an operator can repair it from /api/v1/admin/jobs. Stopping the scheduler
    is unconditional because even a paused one holds a jobstore connection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from sqlalchemy import text

from app.db.session import dispose_engine, get_engine, get_session_factory
from app.jobs import register_jobs, register_tasks
from app.scheduler import (
    get_scheduler,
    start_scheduler,
    start_scheduler_paused,
    stop_scheduler,
)
from app.services import settings_store
from app.settings import get_settings

log = structlog.get_logger("scout.lifespan")

# Recorded at startup; the /diagnostics uptime panel reads it.
PROCESS_START_TIME: datetime | None = None


def _redacted_settings_dump(settings) -> dict[str, object]:
    """Pydantic ``model_dump`` minus the SecretStr surfaces.

    Logged at startup so misconfiguration ("why isn't this connecting?") is
    one log entry away. SecretStrs are redacted by Pydantic itself — they
    show as ``**********`` when dumped.
    """
    return settings.model_dump(mode="json")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Yielded once per app boot. Startup before yield; shutdown after."""
    global PROCESS_START_TIME
    PROCESS_START_TIME = datetime.now(tz=UTC)
    settings = get_settings()
    log.info("scout.starting", config=_redacted_settings_dump(settings))

    # Probe the DB. Failing here means the api refuses to come up if Postgres
    # is down, which is what the compose healthcheck contract expects.
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("scout.db_ok")
    except Exception as exc:
        log.error("scout.db_unreachable", error=str(exc))
        # Re-raise so uvicorn exits non-zero and compose restarts us.
        raise

    # Load runtime settings overrides from the DB (P3 UX work). Done after
    # the DB probe so we don't try to read a table that doesn't exist yet.
    try:
        async with get_session_factory()() as session:
            await settings_store.load_from_db(session)
        get_settings.cache_clear()
        # Re-dump settings now that overrides have merged in.
        log.info(
            "scout.settings_store.ready",
            count=len(settings_store.current()),
        )
    except Exception as exc:
        log.warning("scout.settings_store.load_failed", error=str(exc))

    # Keep the overrides fresh: DB is the source of truth for runtime
    # config, and PATCHes can land on any replica. The refresh loop makes
    # key rotations reach this process within settings_refresh_seconds.
    settings_store.start_refresh_task()

    # Scheduler. Started AFTER the DB probe so a failed boot doesn't leave
    # a half-started scheduler. All three modes are handled explicitly:
    #
    #   embedded   — this API process also fires jobs. Right for a single
    #                replica (local dev, single-pod installs).
    #   disabled   — API pods in an HPA-scaled deploy. Attach the shared
    #                jobstore PAUSED so "run now" endpoints can enqueue for
    #                the standalone scheduler, but fire nothing here.
    #   standalone — reserved for `python -m app.scheduler_standalone`. An
    #                API process must NOT start a scheduler in this mode:
    #                it would win the leader lock and starve the dedicated
    #                scout-scheduler Deployment, silently stopping every
    #                cron job.
    mode = get_settings().scheduler_mode

    # BEFORE the mode branch, deliberately. Every API process queues work —
    # a conference create enqueues an enrich-and-match — and in `standalone`
    # mode this process never starts a scheduler at all. Registering inside
    # the embedded branch would leave those replicas unable to queue
    # anything, with a KeyError naming a task that exists.
    register_tasks()

    if mode == "embedded":
        try:
            if start_scheduler():
                # The schedule lives in app/scheduler.py, not in the scheduler —
                # keeping the task imports out of scheduler.py is what stops
                # services -> scheduler -> tasks -> services cycling.
                register_jobs(get_scheduler())
        except Exception as exc:
            # Don't block API startup on a scheduler-only failure — the
            # manual routes still work without it, and operators can
            # repair via ``/api/v1/admin/jobs``.
            log.error("scout.scheduler_failed", error=str(exc))
    else:
        try:
            start_scheduler_paused()
        except Exception as exc:
            log.error("scout.scheduler_paused_failed", error=str(exc))
        log.info(
            "scout.scheduler_not_started_here",
            scheduler_mode=mode,
            reason="jobstore attached (paused) for enqueue_now; jobs fire elsewhere",
        )

    yield

    # Shutdown
    log.info("scout.shutting_down")
    await settings_store.stop_refresh_task()
    # Unconditional: disabled-mode pods hold a paused scheduler whose
    # jobstore connection also deserves a clean shutdown. Idempotent.
    try:
        stop_scheduler()
    except Exception as exc:
        log.warning("scout.scheduler_shutdown_failed", error=str(exc))
    await dispose_engine()
