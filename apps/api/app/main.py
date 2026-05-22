"""Scout FastAPI entry point.

Plan 02 shipped a minimum healthz + static SPA mount.
Plan 06 (this revision) adds:
  * settings-driven configuration via Pydantic
  * structlog JSON output with request_id propagation + redaction
  * RFC 7807 problem+json error responses
  * lifespan that probes the database at startup
  * /api/v1/readyz that reports DB reachability
  * CORS middleware (only relevant during dev when Vite runs separately)

Plan 12 added the PDF/RAG ingest endpoint.
Plan 13 wires APScheduler start/stop to the lifespan + admin job routes.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    admin_embeddings,
    admin_extraction,
    admin_jobs,
    admin_llm,
    admin_matcher,
    agent,
    audiences,
    conference_series,
    conferences,
    diagnostics,
    graph,
    health,
    messaging,
    notifications,
    past_conferences,
    smes,
    sources,
    topics,
    uploads,
    versions,
)
from app.lifespan import lifespan
from app.logging import configure_logging
from app.middleware.error_handler import install_error_handlers
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
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
# Plan 29: browser security headers (CSP, HSTS, X-Frame-Options,
# Referrer-Policy, Permissions-Policy, X-Content-Type-Options) on every
# response.
app.add_middleware(SecurityHeadersMiddleware)

install_error_handlers(app)

# ---- routers --------------------------------------------------------------
app.include_router(health.router)
app.include_router(messaging.router)
app.include_router(audiences.router)
app.include_router(smes.router)
app.include_router(past_conferences.router)
app.include_router(conferences.router)
app.include_router(conference_series.router)
app.include_router(sources.router)
app.include_router(graph.router)
app.include_router(topics.router)
app.include_router(admin_llm.router)
app.include_router(admin_embeddings.router)
app.include_router(admin_extraction.router)
app.include_router(admin_jobs.router)
app.include_router(admin_matcher.router)
app.include_router(agent.router)
app.include_router(notifications.router)
app.include_router(versions.router)
app.include_router(diagnostics.router)
app.include_router(uploads.router)

# ---- static SPA at / -----------------------------------------------------
# Mount the built assets under /assets, then add a SPA fallback that serves
# index.html for any non-/api path that doesn't match a file. StaticFiles
# alone (even with html=True) only serves index.html for directory roots,
# which 404s on client-side routes like /dashboard or /conferences/<uuid>.
if STATIC_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIR / "assets"),
        name="spa-assets",
    )
    _INDEX_HTML = STATIC_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request) -> FileResponse:
        # /api/* is handled by the routers above; if a request reaches the
        # SPA fallback under /api/, that's a 404, not a fall-through to the
        # SPA shell — return a clean 404 so API consumers see RFC 7807, not HTML.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        # Serve any literal file that exists (e.g. favicon.ico) before
        # falling through to index.html for client-side routes.
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_INDEX_HTML)
