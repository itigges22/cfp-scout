"""/api/v1/admin/jobs — inspect + manually fire scheduled jobs (plan 13).

Endpoints:
    GET  /admin/jobs              — registered jobs + next fire times
    GET  /admin/jobs/runs         — recent ingest_jobs rows
    POST /admin/jobs/heartbeat    — trigger the heartbeat task immediately

Single-user / no auth (per ADR-0001) but every trigger is rate-limited at the
function level (one fire per 30s per job-id) so an accidental hammer doesn't
flood the jobstore. Plan 26's ``/diagnostics`` page will wrap this in UI.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.db.models.ops import IngestJob
from app.db.session import DbSession
from app.scheduler import enqueue_now, get_scheduler
from app.tasks.build_cfp_digest import build_cfp_digest_task
from app.tasks.heartbeat import heartbeat as heartbeat_task

log = structlog.get_logger("scout.api.admin_jobs")
router = APIRouter(prefix="/api/v1/admin/jobs", tags=["admin.jobs"])


# Per-process rate-limit table. Maps ``job-id -> last_trigger_epoch``.
# 30s lockout is plenty for human use; a single-user install will never
# legitimately want to fire the same task twice in that window.
_RATE_LIMIT_WINDOW_S = 30.0
_last_triggered: dict[str, float] = {}


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    last = _last_triggered.get(key, 0.0)
    if now - last < _RATE_LIMIT_WINDOW_S:
        wait = _RATE_LIMIT_WINDOW_S - (now - last)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Job {key!r} was triggered recently; try again in {wait:.1f}s.",
        )
    _last_triggered[key] = now


@router.get("")
async def list_jobs() -> dict:
    """All registered (cron + ad-hoc-still-pending) jobs.

    APScheduler's view of the jobstore — not the run history. Use
    ``/runs`` for that.
    """
    scheduler = get_scheduler()
    if not scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "func": f"{job.func.__module__}.{job.func.__name__}",
                "trigger": str(job.trigger),
                "next_run_time": (
                    job.next_run_time.isoformat() if job.next_run_time else None
                ),
                "coalesce": job.coalesce,
                "max_instances": job.max_instances,
                "misfire_grace_time": job.misfire_grace_time,
            }
        )
    return {
        "running": True,
        "timezone": str(scheduler.timezone),
        "jobs": jobs,
    }


@router.get("/runs")
async def list_runs(db: DbSession, limit: int = 50) -> dict:
    """Recent ``app.ingest_jobs`` rows — successes + failures.

    Filterable by passing ``?limit=N`` (default 50, hard-capped at 500).
    """
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    result = await db.execute(
        select(IngestJob).order_by(IngestJob.started_at.desc().nullslast()).limit(limit)
    )
    rows = result.scalars().all()
    return {
        "limit": limit,
        "runs": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "status": row.status,
                "started_at": _iso(row.started_at),
                "finished_at": _iso(row.finished_at),
                "duration_ms": (row.stats or {}).get("duration_ms"),
                "stats": row.stats,
                "error_text": row.error_text,
            }
            for row in rows
        ],
    }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.post("/heartbeat/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_heartbeat() -> dict:
    """Fire the heartbeat task immediately (in addition to its 10-min cron).

    Useful to verify the scheduler from curl without waiting for the next
    scheduled fire. Rate-limited to one trigger per 30s per job-id.
    """
    _check_rate_limit("heartbeat")
    job_id = enqueue_now(heartbeat_task, job_id="heartbeat-manual")
    log.info("admin.jobs.heartbeat_triggered", job_id=job_id)
    return {"queued_job_id": job_id, "kind": "heartbeat"}


@router.post("/build_cfp_digest/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_cfp_digest() -> dict:
    """Fire the CFP digest builder immediately (plan 24).

    Rate-limited to one trigger per 30s. Useful for verifying the digest
    after edits to ``cfp_deadlines`` without waiting for the 09:00 cron.
    """
    _check_rate_limit("cfp_digest")
    job_id = enqueue_now(build_cfp_digest_task, job_id="cfp-digest-manual")
    log.info("admin.jobs.cfp_digest_triggered", job_id=job_id)
    return {"queued_job_id": job_id, "kind": "build_cfp_digest"}
