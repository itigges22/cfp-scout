"""Scout FastAPI entry point.

Plan 02 shipped a minimum healthz + static SPA mount.
Plan 06 (this revision) adds:
  * settings-driven configuration via Pydantic
  * structlog JSON output with request_id propagation + redaction
  * RFC 7807 problem+json error responses
  * lifespan that probes the database at startup
  * /api/v1/readyz that reports DB reachability
  * CORS middleware (only relevant during dev when Vite runs separately)

Plan 12 will add Docling model warm-up to the lifespan.
Plan 13 will add APScheduler start/stop to the lifespan.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    admin_embeddings,
    admin_llm,
    audiences,
    health,
    messaging,
    past_conferences,
    smes,
    topics,
    uploads,
)
from app.lifespan import lifespan
from app.logging import configure_logging
from app.middleware.error_handler import install_error_handlers
from app.middleware.request_id import RequestIDMiddleware
from app.settings import get_settings

# ---------------------------------------------------------------------------
# Configure logging FIRST, before anything else in the module body tries to
# emit a log line.
# ---------------------------------------------------------------------------
_settings = get_settings()
configure_logging(level=_settings.log_level, fmt=_settings.log_format)

STATIC_DIR = Path(__file__).parent.parent / "static"

# ---------------------------------------------------------------------------
# App factory pattern even though we only create one app — keeps tests clean.
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Scout API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ---- middleware (order matters; CORS first so it wraps everything else) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)

install_error_handlers(app)

# ---- routers --------------------------------------------------------------
app.include_router(health.router)
app.include_router(messaging.router)
app.include_router(audiences.router)
app.include_router(smes.router)
app.include_router(past_conferences.router)
app.include_router(topics.router)
app.include_router(admin_llm.router)
app.include_router(admin_embeddings.router)
app.include_router(uploads.router)

# ---- static SPA at / (FastAPI's StaticFiles, html=True for SPA fallback) --
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
