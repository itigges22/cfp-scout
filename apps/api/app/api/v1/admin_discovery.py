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
