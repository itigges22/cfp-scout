"""Background CFP digest task (plan 24).

Two entry points:

  * :func:`build_cfp_digest_task` — single run; wrapped via ``run_as_job``
    so each run lands an ``app.ingest_jobs`` row with the bucket counts.
    Used by the daily cron AND by the manual admin trigger.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.db.session import get_session_factory
from app.services.digest import build_cfp_digest
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.digest")


async def _do_build() -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await build_cfp_digest(session)
        await session.commit()
    return result.to_stats()


async def build_cfp_digest_task() -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job`."""
    return await run_as_job("build_cfp_digest", _do_build)
