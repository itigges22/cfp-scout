"""/api/v1/admin/discovery — autonomous conference discovery (plan 35).

Endpoints
  * ``POST /api/v1/admin/discovery/run-now``         — sync; returns the
                                                       full DiscoveryResult.
                                                       Blocks for the
                                                       duration of the run.
  * ``POST /api/v1/admin/discovery/run-now-async``   — fire-and-forget via
                                                       the in-process
                                                       scheduler. Returns
                                                       the queued job id.

The discovery feature is gated on the ``discovery_enabled`` setting; both
endpoints refuse 503 when disabled.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, Field

from app.db.session import DbSession
from app.scheduler import enqueue_now
from app.services.web_discovery import run_discovery
from app.services.web_discovery.feeds import (
    FeedFilters,
    ingest_developers_events,
)
from app.settings import get_settings

log = structlog.get_logger("scout.api.admin_discovery")
router = APIRouter(prefix="/api/v1/admin/discovery", tags=["admin.discovery"])


class DiscoveryRunRequest(BaseModel):
    prompt: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "Override the default template prompt for this run. If omitted, "
            "uses `settings.discovery_template_prompt`."
        ),
    )
    max_results: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Override settings.discovery_max_results_per_run for this run.",
    )


@router.post("/run-now")
async def run_now(
    db: DbSession,
    body: Annotated[DiscoveryRunRequest, Body()] = DiscoveryRunRequest(),
) -> dict:
    """Run discovery synchronously and return the full result."""
    settings = get_settings()
    if not settings.discovery_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="discovery_enabled is false; toggle it in /settings/tunables",
        )
    log.info(
        "admin.discovery.run_now",
        prompt_chars=len(body.prompt or settings.discovery_template_prompt),
        max_results=body.max_results,
    )
    result = await run_discovery(
        db,
        prompt=body.prompt or "",
        max_results=body.max_results,
    )
    return result.to_dict()


@router.post("/run-now-async", status_code=status.HTTP_202_ACCEPTED)
async def run_now_async(
    body: Annotated[DiscoveryRunRequest, Body()] = DiscoveryRunRequest(),
) -> dict:
    settings = get_settings()
    if not settings.discovery_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="discovery_enabled is false; toggle it in /settings/tunables",
        )

    from app.tasks.run_discovery import run_discovery_task

    job_id = enqueue_now(
        run_discovery_task,
        job_id="discovery-run-manual",
        kwargs={
            "prompt": body.prompt,
            "max_results": body.max_results,
        },
    )
    return {"queued_job_id": job_id}


# ---------------------------------------------------------------------------
# Structured-feed ingestion (developers.events JSON — plan 35.3)
# ---------------------------------------------------------------------------
class FeedIngestRequest(BaseModel):
    only_ai: bool = Field(
        default=True,
        description="Filter to AI/ML/data events only. Off = ingest everything.",
    )
    future_only: bool = Field(
        default=True,
        description="Skip events whose start_date is in the past.",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=10000,
        description="Cap how many filtered events get persisted this run. Null = unlimited.",
    )


@router.post("/ingest-feed")
async def ingest_feed(
    db: DbSession,
    body: Annotated[FeedIngestRequest, Body()] = FeedIngestRequest(),
) -> dict:
    """Pull the developers.events JSON feed and create Conference rows
    for every matching event. No LLM extraction — the feed is already
    structured. Way cheaper than the scrape+extract path."""
    result = await ingest_developers_events(
        db,
        filters=FeedFilters(
            only_ai=body.only_ai,
            future_only=body.future_only,
            limit=body.limit,
        ),
        actor_label="ingest_feed_manual",
    )
    return result.to_dict()
