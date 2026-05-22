"""Health + readiness endpoints.

``/api/v1/healthz`` — liveness; 200 if the worker process is up.
``/api/v1/readyz``  — readiness; 200 only when downstream deps are reachable.

The compose healthcheck targets healthz. Orchestrators that distinguish
between "alive but not ready" (kubelet probes, OpenShift) use readyz too.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import DbSession

log = structlog.get_logger("scout.health")

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Liveness probe. Returns 200 if the worker is up. Does NOT touch the DB."""
    return {"ok": True}


@router.get("/readyz")
async def readyz(db: DbSession) -> JSONResponse:
    """Readiness probe. 200 only if Postgres responds.

    Later plans expand this to verify the embedding-model row exists
    (plan 11), then the MaaS endpoint is reachable (plan 10). For pass 1
    of plan 06 we check Postgres only — that's the dependency we have wired.
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

