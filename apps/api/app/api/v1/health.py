"""Health and readiness endpoints.

`healthz` is process liveness (always 200 if the worker is up).
`readyz` lands in step 06 with a real DB-reachable check.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Liveness probe. Returns 200 as long as the worker process is up."""
    return {"ok": True}
