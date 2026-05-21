"""Scout FastAPI entry point.

Plan 02 ships the minimum:
  * /api/v1/healthz
  * static mount at / serving the built SPA (or the placeholder in plan 02)

Plan 06 expands this with:
  * structured logging middleware
  * request_id propagation
  * RFC 7807 problem+json error handler
  * Alembic-managed DB schema + /api/v1/readyz
  * CORS configuration
  * lifespan that starts the APScheduler (plan 13)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1 import health

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(
    title="Scout API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.include_router(health.router)

# Serve the built SPA at /. `html=True` makes StaticFiles fall back to index.html
# for unknown paths, which is what an SPA router needs.
# StaticFiles itself prevents path traversal — see FastAPI/Starlette docs.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
