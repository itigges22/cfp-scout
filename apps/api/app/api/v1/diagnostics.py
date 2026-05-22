"""/api/v1/diagnostics — operational dashboard data (plan 26).

Endpoints:
  * ``GET  /diagnostics``                — full 6-panel payload (30s cache)
  * ``POST /diagnostics/refresh``        — admin: invalidate the cache
  * ``POST /diagnostics/jobs/{id}/retry`` — re-enqueue a failed task

The retry endpoint inspects ``app.ingest_jobs.kind`` + ``stats`` and
re-enqueues the matching task with the same kwargs. Rate-limited 1/10s
per job-id.
"""

from __future__ import annotations

import time
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status

from app.db.models.ops import IngestJob
from app.db.session import DbSession
from app.scheduler import enqueue_now
from app.services.diagnostics import build_diagnostics, invalidate_cache

log = structlog.get_logger("scout.api.diagnostics")
router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

# Per-process retry rate-limit. Keys are ingest_jobs.id strings; values
# are monotonic timestamps of the last retry. 10s lockout is enough to
# stop accidental double-clicks without making humans wait long.
_RETRY_WINDOW_S = 10.0
_last_retry: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------
@router.get("")
async def diagnostics(db: DbSession) -> dict:
    """Full diagnostics payload. 30s cache."""
    return await build_diagnostics(db)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh() -> None:
    """Drop the cache so the next request rebuilds."""
    invalidate_cache()
    log.info("diagnostics.cache.invalidated_manual")
    return None


# ---------------------------------------------------------------------------
# Job retry
# ---------------------------------------------------------------------------
# Map ingest_jobs.kind -> (importable target, kwarg-builder).
# kwarg-builder receives the stats dict from the old run and returns the
# kwargs dict for the new enqueue. Most tasks store their primary key in
# stats so re-enqueue is trivial.
def _kwargs_for(kind: str, stats: dict | None) -> dict:
    stats = stats or {}
    if kind == "scrape_source":
        return {"source_id": stats.get("source_id")}
    if kind == "parse_raw_page":
        return {"raw_page_id": stats.get("raw_page_id")}
    if kind.startswith("embed_owner:") or kind == "embed_owner":
        return {
            "owner_type": stats.get("owner_type"),
            "owner_id": stats.get("owner_id"),
            "text": "",  # caller bypassed; not great for retry
        }
    if kind == "run_fit_match":
        return {"conference_id": stats.get("conference_id")}
    if kind == "sme_fit_narrative":
        return {
            "conference_id": stats.get("conference_id"),
            "force": False,
        }
    return {}


def _import_task(kind: str):
    """Return the APScheduler-callable for a given ingest_jobs.kind, or
    None if we don't have a retry path for it."""
    if kind == "scrape_source":
        from app.tasks.scrape_source import scrape_source_task

        return scrape_source_task
    if kind == "parse_raw_page":
        from app.tasks.parse_raw_page import parse_raw_page_task

        return parse_raw_page_task
    if kind == "run_fit_match":
        from app.tasks.run_fit_match import run_fit_match_task

        return run_fit_match_task
    if kind == "sme_fit_narrative":
        from app.tasks.compute_sme_fit_narrative import (
            compute_sme_fit_narrative_task,
        )

        return compute_sme_fit_narrative_task
    if kind == "build_cfp_digest":
        from app.tasks.build_cfp_digest import build_cfp_digest_task

        return build_cfp_digest_task
    if kind == "run_decay_pass":
        from app.tasks.run_decay_pass import run_decay_pass_task

        return run_decay_pass_task
    if kind == "heartbeat":
        from app.tasks.heartbeat import heartbeat

        return heartbeat
    return None


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(db: DbSession, job_id: UUID) -> dict:
    """Re-enqueue an ingest_jobs entry by reading its kind + stats.

    Rate-limited 1/10s per job-id. Errors:
      * 404 if the row doesn't exist
      * 409 if the kind has no registered retry path
      * 429 if retried within the last 10 seconds
    """
    key = str(job_id)
    now = time.monotonic()
    last = _last_retry.get(key, 0.0)
    if now - last < _RETRY_WINDOW_S:
        wait = _RETRY_WINDOW_S - (now - last)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Retry rate-limited; wait {wait:.1f}s.",
        )

    row = await db.get(IngestJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No ingest_job {job_id}")

    target = _import_task(row.kind)
    if target is None:
        raise HTTPException(
            status_code=409,
            detail=f"No retry handler registered for kind={row.kind!r}.",
        )
    kwargs = _kwargs_for(row.kind, row.stats)
    _last_retry[key] = now
    new_job_id = enqueue_now(
        target,
        # Distinct ad-hoc id so APScheduler doesn't collapse with any
        # in-flight job under the same target.
        job_id=f"retry-{job_id}",
        kwargs=kwargs,
    )
    log.info(
        "diagnostics.job.retry",
        original_id=str(job_id),
        kind=row.kind,
        new_job_id=new_job_id,
    )
    return {
        "queued_job_id": new_job_id,
        "original_ingest_job_id": str(job_id),
        "kind": row.kind,
    }
