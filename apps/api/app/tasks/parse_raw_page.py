"""Background extraction task (plan 15).

Two entry points:

  * :func:`parse_raw_page_task(raw_page_id)` — runs the full extraction
    pipeline for one raw_page. Enqueued by the scraper after a successful
    fetch (see :mod:`app.services.scraper.fetch`) and by the admin
    ``POST /api/v1/admin/extraction/parse-now/{id}`` route.

Both JSON-friendly so APScheduler's persistent jobstore can pickle kwargs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.db.session import get_session_factory
from app.services.extraction import parse_raw_page
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.parse")


async def _do_parse(*, raw_page_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await parse_raw_page(session, UUID(raw_page_id))
        await session.commit()
    return result.to_stats()


async def parse_raw_page_task(*, raw_page_id: str) -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job` so each parse
    lands a typed row in ``app.ingest_jobs``."""
    return await run_as_job(
        "parse_raw_page",
        _do_parse,
        raw_page_id=raw_page_id,
        stats_extra={"raw_page_id": raw_page_id},
    )
