"""Entry point for the dedicated scheduler process.

    $ python -m app.scheduler_standalone

WHAT THIS DOES
    Runs APScheduler against the same Postgres jobstore the API uses, but in
    its own process, so the API can be scaled horizontally without several
    schedulers stepping on each other. It loads the database-backed setting
    overrides exactly as the API's lifespan does (background jobs call the
    LLM client and the matcher, so they need the same live config), starts
    the scheduler, keeps the overrides refreshing, then blocks until
    SIGINT/SIGTERM and shuts down cleanly.

HOW IT CONNECTS
    Called by   the container entrypoint of the ``scout-scheduler``
                Deployment in the Helm chart (replicas fixed at 1). Nothing
                in the API imports it.
    Reads       jobs.apscheduler_jobs, app.app_setting_overrides
    Helpers     app/scheduler.py, app/db/session.py,
                services/settings_store/settings_store.py, services/settings_store/settings_store.py
    Tuning      settings.scheduler_mode must be ``standalone`` (or
                ``embedded``); the API side runs ``disabled``

WORTH KNOWING
    Two exits are deliberately loud. Code 2 when SCHEDULER_MODE=disabled,
    which is the API's setting and would leave the fleet with no scheduler
    at all. Code 3 when another process holds the leader advisory lock:
    this process exists only to be the leader, so passive means failure.

    Exiting on a lost lock rather than waiting matters because the lock
    belongs to a Postgres session, and a force-killed predecessor's session
    can hold it for hours until TCP keepalive reaps it. The liveness probe
    is only ``pgrep -f scheduler_standalone``, so a process that blocked
    instead would look healthy while every cron job stayed stopped;
    crash-looping is visible.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress

import structlog

from app.db.session import dispose_engine, get_session_factory
from app.jobs import register_jobs, register_tasks
from app.scheduler import (
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)
from app.services import settings_store
from app.settings import get_settings

log = structlog.get_logger("scout.scheduler_standalone")


async def _bootstrap_db_settings() -> None:
    """Mirror the API lifespan's settings-overrides load. The scheduler
    needs the same operator-configured settings (LLM keys, gate
    thresholds, etc.) the API does, because the background jobs it
    runs call directly into the matcher + LLM client."""
    factory = get_session_factory()
    async with factory() as s:
        await settings_store.load_from_db(s)
    get_settings.cache_clear()


async def _run_forever(stop: asyncio.Event) -> None:
    """Block until a stop signal arrives. ``asyncio.Event.wait()`` is
    cancellation-friendly so SIGINT/SIGTERM unblock cleanly."""
    await stop.wait()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    def _handler(signame: str) -> None:
        log.info("scout.scheduler_standalone.signal", signal=signame)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            # add_signal_handler raises on Windows; we run on Linux
            # containers in prod so this is fine, but suppress for
            # local-mac dev where someone might python -m this.
            loop.add_signal_handler(sig, _handler, sig.name)


async def main() -> int:
    log.info("scout.scheduler_standalone.starting")
    await _bootstrap_db_settings()

    settings = get_settings()
    if settings.scheduler_mode == "disabled":
        log.error(
            "scout.scheduler_standalone.misconfigured",
            scheduler_mode=settings.scheduler_mode,
            hint=(
                "SCHEDULER_MODE=disabled is the API-side setting. The "
                "scheduler process should run with SCHEDULER_MODE=standalone "
                "(or embedded — either lets the scheduler start)."
            ),
        )
        return 2

    # This process exists solely to BE the scheduler, so failing to win the
    # leader lock is fatal here — unlike an API worker, where going passive
    # is the normal outcome.
    #
    # The lock is held by a Postgres session, and a SIGKILLed predecessor's
    # session survives until TCP keepalive reaps it (hours, by default). So
    # the replacement pod would previously log one INFO line, block forever
    # in _run_forever(), and report "ready" — while `pgrep -f
    # scheduler_standalone` kept the liveness probe green and every cron
    # job silently stopped. Exiting non-zero makes the pod crash-loop
    # visibly instead.
    register_tasks()
    started = start_scheduler()
    if not started:
        log.error(
            "scout.scheduler_standalone.not_leader",
            hint=(
                "another process holds the scheduler advisory lock. If the "
                "previous scheduler pod was force-killed, its Postgres "
                "session may still hold it; it is released when that "
                "session is reaped."
            ),
        )
        await dispose_engine()
        return 3

    # The schedule lives in app/scheduler.py, deliberately separate from the
    # scheduler itself — that separation is what keeps app/services free of
    # any import back into the task layer.
    register_jobs(get_scheduler())

    # Background jobs call the LLM client directly, so this process must
    # also see key rotations / model swaps written to the DB by the api.
    settings_store.start_refresh_task()
    log.info(
        "scout.scheduler_standalone.ready",
        scheduler_mode=settings.scheduler_mode,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, stop)
    try:
        await _run_forever(stop)
    finally:
        log.info("scout.scheduler_standalone.shutting_down")
        await settings_store.stop_refresh_task()
        try:
            stop_scheduler()
        except Exception as exc:
            log.warning("scout.scheduler_standalone.stop_failed", error=str(exc))
        await dispose_engine()
    log.info("scout.scheduler_standalone.exited")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
