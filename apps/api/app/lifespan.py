"""FastAPI lifespan hook — startup and shutdown.

Plan 06 wires:
  * DB connectivity check (fail loud if Postgres unreachable)
  * Settings dump at startup (redacted by structlog's redact processor)

Plan 13 wires:
  * APScheduler start (after the DB probe succeeds) + shutdown on app exit

Plan 12 will add:
  * Docling model warm-up (load layout models so first PDF upload doesn't pay the cost)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from sqlalchemy import text

from app.db.session import dispose_engine, get_engine
from app.scheduler import start_scheduler, stop_scheduler
from app.services.lifecycle import register_versioning_listeners
from app.settings import get_settings

log = structlog.get_logger("scout.lifespan")

# Recorded at startup; consumed by plan 26's /diagnostics for uptime.
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
        from app.db.session import get_session_factory
        from app.services import settings_overrides

        async with get_session_factory()() as session:
            await settings_overrides.load_from_db(session)
        get_settings.cache_clear()
        # Re-dump settings now that overrides have merged in.
        log.info(
            "scout.settings_overrides.ready",
            count=len(settings_overrides.current()),
        )
    except Exception as exc:
        log.warning("scout.settings_overrides.load_failed", error=str(exc))

    # Keep the overrides fresh: DB is the source of truth for runtime
    # config, and PATCHes can land on any replica. The refresh loop makes
    # key rotations reach this process within settings_refresh_seconds.
    from app.services import settings_refresh

    settings_refresh.start_refresh_task()

    # Plan 25: register the content-versioning SQLAlchemy event listener.
    # Idempotent — safe to call on every boot. Done BEFORE the scheduler
    # so any startup task that mutates versioned entities gets logged.
    register_versioning_listeners()
    log.info("scout.versioning.ready")

    # Scheduler runs in-process by default. Started AFTER the DB probe
    # so a failed boot doesn't leave a half-started scheduler.
    #
    # In HPA-scaled OpenShift deploys, set ``SCHEDULER_MODE=disabled``
    # on the API pods so they don't all run their own schedulers (which
    # would each contend for the same Postgres jobstore rows). A
    # separate ``scout-scheduler`` Deployment runs the scheduler
    # singleton with ``SCHEDULER_MODE=standalone`` via
    # ``python -m app.scheduler_standalone``.
    from app.settings import get_settings as _gs

    mode = _gs().scheduler_mode
    if mode == "disabled":
        # Don't fire jobs here — but DO attach the shared jobstore
        # (paused) so admin "run now" endpoints can enqueue work for
        # the standalone scheduler. Without this, enqueue_now() buffers
        # jobs in process-local memory and they silently never run.
        from app.scheduler import start_scheduler_paused

        try:
            start_scheduler_paused()
        except Exception as exc:
            log.error("scout.scheduler_paused_failed", error=str(exc))
        log.info("scout.scheduler_skipped", reason="SCHEDULER_MODE=disabled (jobstore attached, paused)")
    else:
        try:
            start_scheduler()
        except Exception as exc:
            log.error("scout.scheduler_failed", error=str(exc))
            # Don't block API startup on a scheduler-only failure — the
            # manual routes still work without it, and operators can
            # repair via ``/api/v1/admin/jobs``.

    yield

    # Shutdown
    log.info("scout.shutting_down")
    await settings_refresh.stop_refresh_task()
    # Unconditional: disabled-mode pods hold a paused scheduler whose
    # jobstore connection also deserves a clean shutdown. Idempotent.
    try:
        stop_scheduler()
    except Exception as exc:
        log.warning("scout.scheduler_shutdown_failed", error=str(exc))
    await dispose_engine()
