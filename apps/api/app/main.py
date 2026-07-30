"""The FastAPI application object — everything the web server serves.

WHAT THIS DOES
    Builds the single ``app`` object uvicorn runs. Configures logging first,
    creates the FastAPI instance, wraps it in four middlewares, registers 28
    routers under /api/v1, then mounts the built React single-page app (SPA)
    at / so one process serves both the JSON API and the UI. Anything that
    is not under /api/ and is not a real file on disk falls through to
    index.html, which is what makes client-side routes such as
    /conferences/<uuid> survive a hard refresh.

HOW IT CONNECTS
    Called by   uvicorn (``uvicorn app.main:app`` — the Containerfile CMD);
                tests/integration/conftest.py and
                tests/unit/test_spa_fallback_traversal.py import ``app``
    Reads       apps/api/static/ (the Vite build: index.html + assets/).
                No database access at import time.
    Helpers     app/lifespan.py, app/logging.py, app/api/v1/*.py,
                app/middleware.py, app/middleware.py
    Tuning      settings.log_level, log_format, cors_origins

WORTH KNOWING
    ``add_middleware`` PREPENDS, so the last one added is the OUTERMOST. The
    real order is Auth -> SecurityHeaders -> RequestID -> CORS -> router,
    the reverse of how the calls read. Starlette's ServerErrorMiddleware
    sits outside all four, so an unhandled 500 carries no CORS headers, no
    X-Request-ID and no Content-Security-Policy; 4xx responses are fine.

    The catch-all SPA route resolves the requested path and requires it to
    stay under the static root before serving a file. ``full_path`` arrives
    percent-decoded, so "%2e%2e/%2e%2e/etc/passwd" reaches the handler as
    "../../etc/passwd"; without that check the route serves any file on
    disk, unauthenticated. Paths that escape fall through to the SPA shell
    rather than 404, so probing cannot tell the two cases apart.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    admin,
    agent,
    conferences,
    ops,
    people,
    positioning,
    reports,
    sources,
    taxonomy,
    uploads,
)
from app.lifespan import lifespan
from app.logging import configure_logging
from app.middleware import (
    AuthMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    install_error_handlers,
)
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

# ---- middleware ----------------------------------------------------------
# Order matters, and it is the REVERSE of what it looks like:
# ``add_middleware`` PREPENDS, so the last one added ends up outermost.
# The resulting stack (outermost first) is:
#
#   Auth -> SecurityHeaders -> RequestID -> CORS -> router
#
# Consequence worth knowing: unhandled 500s are rendered by Starlette's
# ServerErrorMiddleware, which sits OUTSIDE all of these — so a 500 carries
# no CORS headers, no X-Request-ID, and no CSP. 4xx are fine because
# Starlette's ExceptionMiddleware sits inside them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
# Browser security headers (CSP, HSTS, X-Frame-Options,
# Referrer-Policy, Permissions-Policy, X-Content-Type-Options) on every
# response.
app.add_middleware(SecurityHeadersMiddleware)
# Reads X-Forwarded-Email / X-Forwarded-User (from the oauth-proxy
# sidecar) and stores it
# on request.state.user_email. Falls back to SCOUT_DEV_USER_EMAIL in dev.
app.add_middleware(AuthMiddleware)

install_error_handlers(app)

# ---- routers --------------------------------------------------------------
app.include_router(ops.router)
app.include_router(positioning.router)
app.include_router(taxonomy.router)
app.include_router(people.router)
app.include_router(conferences.router)
app.include_router(reports.router)
app.include_router(sources.router)
app.include_router(admin.router)
app.include_router(agent.router)
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
    # Resolved once at import so every request compares against a real,
    # symlink-free root.
    _STATIC_ROOT = STATIC_DIR.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request) -> FileResponse:
        # /api/* is handled by the routers above; if a request reaches the
        # SPA fallback under /api/, that's a 404, not a fall-through to the
        # SPA shell — return a clean 404 so API consumers see RFC 7807, not HTML.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        # Serve any literal file that exists (e.g. favicon.ico) before
        # falling through to index.html for client-side routes.
        #
        # ``full_path`` arrives percent-DECODED, so "%2e%2e/%2e%2e/etc/passwd"
        # reaches us as "../../etc/passwd". Resolve the candidate and require
        # it to stay under the static root — otherwise this handler is an
        # unauthenticated arbitrary-file read (StaticFiles, mounted at
        # /assets above, does this check for us; this hand-rolled path did
        # not). Fall through to the SPA shell rather than 404 so probing
        # can't distinguish "escaped the root" from "client-side route".
        candidate = (STATIC_DIR / full_path).resolve()
        if (
            full_path
            and candidate.is_relative_to(_STATIC_ROOT)
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(_INDEX_HTML)
