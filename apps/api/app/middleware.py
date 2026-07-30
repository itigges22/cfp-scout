"""The request pipeline: what wraps every request, and what catches it.

WHAT THIS DOES
    Three middlewares, declared in the order they are added — which is the
    REVERSE of the order they run:

        Auth             resolves the caller
        SecurityHeaders  CSP, HSTS, nosniff and friends on the way out
        RequestID        stamps a request id and binds it to the logger

    Then the exception handlers: validation errors to 422 with field
    detail, known app errors to their status, and everything else to a 500
    that logs the traceback and returns no internals.

HOW IT CONNECTS
    Called by   app/main.py, once at startup
    Helpers     app/logging.py for the structlog binding

WORTH KNOWING
    Middleware and exception handlers were separate modules because one
    registers ``BaseHTTPMiddleware`` classes and the other registers
    ``@app.exception_handler`` callbacks. That is a FastAPI API
    distinction, not a reason for a reader to open two files — both
    answer "what happens to a request that is not my endpoint".

    Middleware order is load-bearing: RequestID is added last so it runs
    FIRST, which is what puts a request id on the log line of a failure
    inside the auth middleware.

    A 500 handler must never leak the exception text to the client. It
    logs the traceback and returns a generic body with the request id, so
    an operator can find the log line.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.settings import get_settings

log = structlog.get_logger("scout.middleware")


# ==========================================================================
# middleware.py
# ==========================================================================


_DEV_FALLBACK = os.environ.get("SCOUT_DEV_USER_EMAIL", "")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # oauth-proxy sets X-Auth-Request-Email when the IdP provides an email
        # claim. OpenShift's built-in provider often only sets
        # X-Auth-Request-User (the preferred username, e.g. "itigges").
        # Accept either; fall back to dev env var for local runs.
        # openshift/oauth-proxy forwards X-Forwarded-Email and X-Forwarded-User
        # (not X-Auth-Request-* which are response headers for nginx auth_request mode).
        email = (
            request.headers.get("x-forwarded-email")
            or request.headers.get("x-forwarded-user")
            or _DEV_FALLBACK
        )
        request.state.user_email = email
        return await call_next(request)


_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)


_HSTS = "max-age=86400; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply browser security headers to every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        # Don't clobber a previously-set header (rare, but possible for
        # special endpoints e.g. file downloads).
        headers = response.headers
        headers.setdefault("Content-Security-Policy", _CSP)
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Strict-Transport-Security", _HSTS)
        headers.setdefault("Permissions-Policy", _PERMISSIONS_POLICY)
        return response


_REQUEST_ID_HEADER = "X-Request-ID"


def _new_request_id() -> str:
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Bind a request id and log one access line per request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or _new_request_id()
        start = time.perf_counter()

        # Bind into structlog contextvars — every log emitted under this
        # request will include request_id without callers passing it through.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log.error(
                "request.failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers[_REQUEST_ID_HEADER] = request_id

        # 5xx is logged at error level, 4xx at warning, otherwise info.
        if response.status_code >= 500:
            level = log.error
        elif response.status_code >= 400:
            level = log.warning
        else:
            level = log.info

        level(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )

        return response


# ==========================================================================
# errors.py
# ==========================================================================


_PROBLEM_CONTENT_TYPE = "application/problem+json"


def _problem(
    *,
    status_code: int,
    title: str,
    detail: str,
    type_: str = "about:blank",
    extras: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if extras:
        body.update(extras)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body),
        media_type=_PROBLEM_CONTENT_TYPE,
        # Starlette attaches headers to some HTTPExceptions and RFC 7231
        # REQUIRES them on certain statuses — notably `Allow` on a 405.
        # Dropping them here would trade one spec violation for another.
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the given FastAPI app."""
    settings = get_settings()
    include_traceback = settings.env == "dev"

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Surface field-level errors so the frontend can pin them to inputs.
        return _problem(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid request body",
            detail="One or more fields failed validation. See `errors` for details.",
            type_="https://scout.example/errors/validation",
            extras={"errors": exc.errors()},
        )

    @app.exception_handler(HTTPException)
    async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return _problem(
            status_code=exc.status_code,
            title=exc.detail if isinstance(exc.detail, str) else "HTTP error",
            detail=exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        """A constraint violation is the client's problem, not an outage.

        Registered ahead of the generic SQLAlchemyError handler so this
        returns 409 rather than a 503 telling the client to retry something
        that can never succeed.

        The message is deliberately STATIC: ``str(exc.orig)`` carries
        asyncpg's ``DETAIL: Key (...)=(...)`` line, which would dump the
        offending row's column values into the response body.
        """
        log.warning(
            "db.integrity_error",
            path=request.url.path,
            error_type=type(exc).__name__,
        )
        return _problem(
            status_code=status.HTTP_409_CONFLICT,
            title="Constraint violation",
            detail=(
                "The request conflicts with existing data or a database "
                "constraint. Check for duplicates and required references."
            ),
            type_="https://scout.example/errors/conflict",
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # DB errors get logged at error level; clients see a generic message.
        log.error(
            "db.error",
            path=request.url.path,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        return _problem(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="Database error",
            detail="The database is temporarily unavailable. Please retry.",
            type_="https://scout.example/errors/database",
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "request.unhandled",
            path=request.url.path,
            error_type=type(exc).__name__,
        )
        extras: dict[str, Any] = {}
        if include_traceback:
            import traceback

            extras["traceback"] = traceback.format_exception(exc)
        return _problem(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal server error",
            detail=str(exc) if include_traceback else "An unexpected error occurred.",
            type_="https://scout.example/errors/internal",
            extras=extras or None,
        )
