"""/api/v1/sources — manage the sites the crawler pulls conference pages from.

WHAT THIS DOES
    A source is one crawlable place: a conference calendar, an
    organization's events page. Endpoints list them (filter by ``enabled``
    and ``kind``), create, fetch, partially update, soft-delete (DELETE only
    sets ``enabled=false``), and ``POST /{id}/crawl-now``, which queues an
    immediate scrape and returns the job id to poll via
    ``/admin/jobs/runs``.

HOW IT CONNECTS
    Called by   main.py (registered as a router). Nothing in apps/web/src
                calls these — sources are managed over the API today.
    Writes      app.sources; crawl-now enqueues tasks.py,
                whose runs are recorded in app.ingest_jobs
    Helpers     services/discovery.py, app/scheduler.py

WORTH KNOWING
    crawl-now 409s on a disabled source and obeys the same politeness rules
    as the scheduled crawl (robots.txt, per-host rate limit). Calling it
    twice in quick succession is safe: both calls collapse onto the same
    ``scrape-<id>`` job id and the in-flight scrape continues, because
    APScheduler is configured with ``replace_existing=True`` and
    ``max_instances=1``.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.db.session import DbSession
from app.scheduler import enqueue_now
from app.schemas import Page, SourceCreate, SourceRead, SourceUpdate
from app.services import discovery
from app.tasks import scrape_source_task

log = structlog.get_logger("scout.api.sources")
router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("", response_model=Page[SourceRead])
async def list_sources(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    enabled: bool | None = None,
    kind: str | None = None,
) -> Page[SourceRead]:
    return await discovery.list_sources(
        db, page=page, per_page=per_page, enabled=enabled, kind=kind
    )


@router.get("/{source_id}", response_model=SourceRead)
async def get_source(db: DbSession, source_id: UUID) -> SourceRead:
    row = await discovery.get_source(db, source_id)
    return SourceRead.model_validate(row)


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(db: DbSession, payload: SourceCreate) -> SourceRead:
    row = await discovery.create_source(db, payload)
    await db.commit()
    return SourceRead.model_validate(row)


@router.patch("/{source_id}", response_model=SourceRead)
async def update_source(db: DbSession, source_id: UUID, payload: SourceUpdate) -> SourceRead:
    row = await discovery.update_source(db, source_id, payload)
    await db.commit()
    return SourceRead.model_validate(row)


@router.delete("/{source_id}", status_code=status.HTTP_200_OK)
async def disable_source(db: DbSession, source_id: UUID) -> dict:
    row = await discovery.disable_source(db, source_id)
    await db.commit()
    return {"id": str(row.id), "enabled": row.enabled}


@router.post("/{source_id}/crawl-now", status_code=status.HTTP_202_ACCEPTED)
async def crawl_now(db: DbSession, source_id: UUID) -> dict:
    """Enqueue an ad-hoc scrape for this source. Returns the queued job id;
    poll ``/admin/jobs/runs?limit=10`` to see progress + completion stats.

    Honors the same politeness rules as the cron pull — robots.txt + per-host
    rate limit. Calling this twice in quick succession is safe; the second
    call collapses into the same ``scrape-<id>`` job_id and the in-flight
    scrape continues (APScheduler's ``replace_existing=True`` + ``max_instances=1``
    handle the dedupe).
    """
    # Existence check up-front so we 404 rather than enqueueing a doomed job.
    src = await discovery.get_source(db, source_id)
    if not src.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Source {source_id} is disabled.",
        )
    job_id = enqueue_now(
        scrape_source_task,
        job_id=f"scrape-{source_id}",
        kwargs={"source_id": str(source_id)},
    )
    log.info("source.crawl_now", source_id=str(source_id), job_id=job_id)
    return {"queued_job_id": job_id, "source_id": str(source_id)}
