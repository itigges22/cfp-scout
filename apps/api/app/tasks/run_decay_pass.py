"""Daily decay-pass task (plan 25).

Bulk-updates conferences.freshness_score + archives ended events.
No-op when ``DECAY_ENABLED=false``.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.db.session import get_session_factory
from app.services.lifecycle import run_decay_pass
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.decay")


async def _do_decay() -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await run_decay_pass(session)
        await session.commit()
    return result.to_stats()


async def run_decay_pass_task() -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job`."""
    return await run_as_job("run_decay_pass", _do_decay)
