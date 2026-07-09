"""Periodic cross-process refresh of DB-backed settings overrides.

``app.app_setting_overrides`` is the source of truth for runtime
configuration (LLM keys, model names, matcher knobs). Each process keeps
an in-memory snapshot (``settings_overrides._OVERRIDES``) that, before
this module existed, was populated exactly once at startup — so a key
rotated through ``PATCH /api/v1/admin/settings`` on one api pod never
reached sibling replicas or the standalone scheduler until they
restarted (the reason the LLM settings carried ``restart_required``).

This loop re-reads the table every ``settings_refresh_seconds`` and
clears the ``get_settings`` cache when anything changed. Consumers pick
the change up on their next read: the LLM client compares a settings
fingerprint on every ``get_llm_client()`` call and rebuilds itself when
the key/URL/model changed, so a rotation propagates to every process
within one refresh interval, no restart.

Both entrypoints run it:
  * api        — started in ``lifespan()``, cancelled on shutdown
  * scheduler  — started in ``scheduler_standalone.main()``
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import structlog

from app.db.session import get_session_factory
from app.services import settings_overrides
from app.settings import get_settings

log = structlog.get_logger("scout.settings_refresh")

_task: asyncio.Task | None = None


async def _refresh_once() -> None:
    async with get_session_factory()() as session:
        changed = await settings_overrides.refresh_from_db(session)
    if changed:
        get_settings.cache_clear()


async def _loop() -> None:
    while True:
        # Re-read the interval each cycle so it is itself tunable.
        interval = get_settings().settings_refresh_seconds
        if interval <= 0:
            # Disabled — park and re-check occasionally in case an
            # operator re-enables it (that change arrives via env/restart
            # or a PATCH handled by this same process).
            await asyncio.sleep(60)
            continue
        await asyncio.sleep(interval)
        try:
            await _refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — keep the loop alive
            log.warning("settings_refresh.failed", error=str(exc))


def start_refresh_task() -> None:
    """Idempotent; call once per process after the initial overrides load."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.get_running_loop().create_task(_loop(), name="settings-refresh")
    log.info(
        "settings_refresh.started",
        interval_seconds=get_settings().settings_refresh_seconds,
    )


async def stop_refresh_task() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with suppress(asyncio.CancelledError):
        await _task
    _task = None
    log.info("settings_refresh.stopped")
