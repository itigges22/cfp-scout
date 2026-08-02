"""Routes that answer "is this thing running, and who am I?".

WHAT THIS DOES
    Liveness and readiness, the current user, and the full diagnostics
    snapshot the admin health page renders.

HOW IT CONNECTS
    Calls       services/diagnostics.py
    Serves      /api/v1/healthz, /api/v1/readyz, /api/v1/me,
                /api/v1/diagnostics*

WORTH KNOWING
    Liveness must stay process-only — if it checks the database, a brief
    database blip restarts every pod instead of just failing readiness.

    The route function was named ``diagnostics`` and shadowed the imported
    ``diagnostics`` service module; the module is now imported as
    ``diagnostics_service``.
"""

from __future__ import annotations

import time
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.db.models import IngestJob
from app.db.session import DbSession
from app.scheduler import enqueue_now
from app.services import diagnostics as diagnostics_service
from app.services.diagnostics import build_diagnostics, invalidate_cache
from app.tasks import (
    build_cfp_digest_task,
    heartbeat,
    parse_raw_page_task,
    run_fit_match_task,
    scrape_source_task,
)

log = structlog.get_logger("scout.api.ops")


# ==========================================================================
# health.py
# ==========================================================================


_r_health = APIRouter(prefix="/api/v1", tags=["health"])


@_r_health.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Liveness probe. Returns 200 if the worker is up. Does NOT touch the DB."""
    return {"ok": True}


@_r_health.get("/readyz")
async def readyz(db: DbSession) -> JSONResponse:
    """Readiness probe. 200 only if Postgres responds.

    Later plans expand this to verify the embedding-model row exists
    Checks Postgres only. That is the dependency whose loss makes every
    write fail, so it is the one readiness must gate on.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("readyz.db_unreachable", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ok": False, "reason": "database_unreachable"},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ==========================================================================
# me.py
# ==========================================================================


_r_me = APIRouter(prefix="/api/v1", tags=["auth"])


class UserRead(BaseModel):
    email: str


@_r_me.get("/me", response_model=UserRead)
async def get_me(request: Request) -> UserRead:
    return UserRead(email=getattr(request.state, "user_email", ""))


# ==========================================================================
# diagnostics.py
# ==========================================================================


_r_diagnostics = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])


_RETRY_WINDOW_S = 10.0


_last_retry: dict[str, float] = {}


@_r_diagnostics.get("")
async def diagnostics(db: DbSession) -> dict:
    """Full diagnostics payload. 30s cache."""
    return await build_diagnostics(db)


@_r_diagnostics.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh() -> None:
    """Drop the cache so the next request rebuilds."""
    invalidate_cache()
    log.info("diagnostics.cache.invalidated_manual")
    return None


@_r_diagnostics.post("/llm-errors/clear", status_code=status.HTTP_200_OK)
async def clear_llm_errors(db: DbSession) -> dict:
    """Hide LLM errors recorded up to now from the diagnostics panel.

    The ``llm_calls`` rows are audit history and stay untouched — this
    just persists a cleared-at watermark (in ``app_setting_overrides``,
    so it survives restarts and syncs across pods) that the LLM panel
    uses to filter its "recent errors" list. New errors after the clear
    still show up.
    """
    from datetime import UTC, datetime


    now_iso = datetime.now(tz=UTC).isoformat()
    await diagnostics_service.set_value(db, "diagnostics_llm_errors_cleared_at", now_iso)
    await db.commit()
    invalidate_cache()
    log.info("diagnostics.llm_errors.cleared", cleared_at=now_iso)
    return {"cleared_at": now_iso}


def _kwargs_for(kind: str, stats: dict | None, job_id: str | None = None) -> dict:
    stats = stats or {}
    if kind in ("talk_upload", "messaging_upload"):
        # The task keeps the source file on failure precisely so this
        # endpoint can re-run extraction against the SAME ingest row.
        from pathlib import Path

        from app.settings import get_settings

        filename = (stats.get("filename") or "").lower()
        if kind == "talk_upload":
            ext = next(
                (e for e in (".pdf", ".docx", ".txt") if filename.endswith(e)), ".pdf"
            )
            path = Path(get_settings().storage_path) / "talk_uploads" / f"{job_id}{ext}"
            out = {"job_id": job_id, "file_path": str(path), "filename": filename}
        else:
            path = (
                Path(get_settings().storage_path) / "messaging_uploads" / f"{job_id}.pdf"
            )
            out = {
                "job_id": job_id,
                "file_path": str(path),
                "filename": filename,
                "doc_kind": stats.get("doc_kind") or "other",
            }
        return out
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
    return {}


def _import_task(kind: str):
    """Return the APScheduler-callable for a given ingest_jobs.kind, or
    None if we don't have a retry path for it."""
    if kind == "scrape_source":

        return scrape_source_task
    if kind == "parse_raw_page":

        return parse_raw_page_task
    if kind == "run_fit_match":

        return run_fit_match_task
    if kind == "build_cfp_digest":

        return build_cfp_digest_task

    if kind == "heartbeat":

        return heartbeat
    if kind == "talk_upload":
        from app.tasks import talk_upload_extract_task

        return talk_upload_extract_task
    if kind == "messaging_upload":
        from app.tasks import messaging_upload_extract_task

        return messaging_upload_extract_task
    return None


@_r_diagnostics.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
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
    kwargs = _kwargs_for(row.kind, row.stats, job_id=str(job_id))
    if row.kind in ("talk_upload", "messaging_upload"):
        from pathlib import Path

        fp = kwargs.get("file_path")
        if not fp or not Path(fp).exists():
            raise HTTPException(
                status_code=409,
                detail=(
                    "The uploaded source file is no longer on shared storage — "
                    "re-upload the document instead of retrying."
                ),
            )
        row.status = "queued"
        row.stats = {**(row.stats or {}), "stage": "queued"}
        row.error_text = None
        await db.commit()
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


router = APIRouter()
router.include_router(_r_health)
router.include_router(_r_me)
router.include_router(_r_diagnostics)
