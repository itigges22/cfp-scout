"""Daily autonomous discovery task (plan 35).

Runs at the configured UTC hour each day (``discovery_cron_hour_utc``,
default 06:00). No-op when ``discovery_enabled=false``.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.db.session import get_session_factory
from app.services.web_discovery import run_discovery
from app.settings import get_settings
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.discovery")


async def _do_discovery(
    *, prompt: str | None = None, max_results: int | None = None
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.discovery_enabled:
        log.info("discovery.task.disabled")
        return {"skipped": True, "reason": "discovery_enabled=false"}

    async with get_session_factory()() as session:
        result = await run_discovery(
            session,
            prompt=prompt or "",
            max_results=max_results,
        )
        await session.commit()
    return result.to_dict()


async def run_discovery_task(
    *, prompt: str | None = None, max_results: int | None = None
) -> dict[str, Any]:
    return await run_as_job(
        "run_discovery",
        _do_discovery,
        prompt=prompt,
        max_results=max_results,
    )
