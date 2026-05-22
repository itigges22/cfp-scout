"""/api/v1/admin/extraction — manually drive the extraction pipeline (plan 15).

Endpoints:

  * ``POST /admin/extraction/parse-now/{raw_page_id}``
        Run the full extraction pipeline synchronously and return the
        :class:`ParseResult` payload. Used for ad-hoc reruns + verification.

  * ``POST /admin/extraction/parse-now-async/{raw_page_id}``
        Enqueue the parse via the scheduler instead of running inline; returns
        the queued job_id. Useful when the page is large and you don't want
        to keep the HTTP request open.

Single-user / no auth (per ADR-0001) but loudly logged via the
``admin.extraction.*`` event names.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, status

from app.db.session import DbSession
from app.scheduler import enqueue_now
from app.services.extraction import parse_raw_page
from app.tasks.parse_raw_page import parse_raw_page_task

log = structlog.get_logger("scout.api.admin_extraction")
router = APIRouter(prefix="/api/v1/admin/extraction", tags=["admin.extraction"])


@router.post("/parse-now/{raw_page_id}")
async def parse_now(db: DbSession, raw_page_id: UUID) -> dict:
    """Run the extraction synchronously and return the :class:`ParseResult`."""
    log.info("admin.extraction.parse_now", raw_page_id=str(raw_page_id))
    result = await parse_raw_page(db, raw_page_id)
    await db.commit()
    return result.to_stats()


@router.post("/parse-now-async/{raw_page_id}", status_code=status.HTTP_202_ACCEPTED)
async def parse_now_async(raw_page_id: UUID) -> dict:
    """Enqueue the parse via the scheduler and return immediately."""
    job_id = enqueue_now(
        parse_raw_page_task,
        job_id=f"parse-{raw_page_id}",
        kwargs={"raw_page_id": str(raw_page_id)},
    )
    log.info("admin.extraction.parse_enqueued", raw_page_id=str(raw_page_id), job_id=job_id)
    return {"queued_job_id": job_id, "raw_page_id": str(raw_page_id)}
