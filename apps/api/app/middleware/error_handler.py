"""RFC 7807 problem+json error responses.

Every error the api returns to a client conforms to RFC 7807. The benefits:

* Consistent shape: clients don't need per-endpoint error parsing.
* The frontend (plan 08) renders the ``detail`` field directly into the
  user-facing toast on 422s.
* The ``errors`` array (added for ValidationError specifically) carries
  field-level breakdowns so the wizard UIs can highlight the offending input.

In production (``ENV=prod``) stack traces are NOT included. In dev they are,
to make local debugging fast.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.settings import get_settings

log = structlog.get_logger("scout.errors")

_PROBLEM_CONTENT_TYPE = "application/problem+json"


def _problem(
    *,
    status_code: int,
    title: str,
    detail: str,
    type_: str = "about:blank",
    extras: dict[str, Any] | None = None,
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
