"""Standalone scheduler entrypoint for the ``scout-scheduler`` Deployment.

Runs APScheduler against the same Postgres jobstore the API uses, but
in a separate process so the API can scale horizontally (HPA) without
multiple scheduler instances stepping on each other.

  $ python -m app.scheduler_standalone

In the OpenShift Helm chart, this is the container entrypoint for the
``scout-scheduler`` Deployment (replicas=1, hardcoded — APScheduler
isn't horizontally scalable). The API Deployment runs with
``SCHEDULER_MODE=disabled`` so its lifespan hook skips scheduler init.

Lifecycle:
  1. Load DB-side settings overrides (matches what the API lifespan does)
  2. Start APScheduler against the Postgres jobstore
  3. Block forever, handling SIGINT/SIGTERM for graceful shutdown
  4. On signal: stop scheduler cleanly, dispose engine, exit 0

Why a separate file vs. ``--scheduler-only`` CLI flag on main.py:
  - Cleaner container entrypoint (single command, no flag parsing)
  - Separate health-check semantics (this process has no /healthz; the
    Kubernetes liveness probe is just ``pgrep -f scheduler_standalone``)
  - Future-proofs swapping the scheduler implementation (Celery,
    Temporal, etc.) without changing the API process.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress

import structlog

from app.db.session import dispose_engine, get_session_factory
from app.scheduler import start_scheduler, stop_scheduler
from app.services import settings_overrides
from app.settings import get_settings

log = structlog.get_logger("scout.scheduler_standalone")


async def _bootstrap_db_settings() -> None:
    """Mirror the API lifespan's settings-overrides load. The scheduler
    needs the same operator-configured settings (LLM keys, gate
    thresholds, etc.) the API does, because the background jobs it
    runs call directly into the matcher + LLM client."""
    factory = get_session_factory()
    async with factory() as s:
        await settings_overrides.load_from_db(s)
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

    start_scheduler()
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
        try:
            stop_scheduler()
        except Exception as exc:  # noqa: BLE001
            log.warning("scout.scheduler_standalone.stop_failed", error=str(exc))
        await dispose_engine()
    log.info("scout.scheduler_standalone.exited")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
