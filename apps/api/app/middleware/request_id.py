"""Request-ID middleware.

Every request gets a stable identifier. The chain:

1. If the client sent an ``X-Request-ID`` header, honour it. Useful for
   correlating across logs when an upstream tool injects one.
2. Otherwise, generate a new UUID4.
3. Bind the id into structlog's contextvars so every log statement made
   during the request automatically carries ``request_id=...``.
4. Echo it back to the client in the ``X-Request-ID`` response header.

Plus: time the request and log a per-request access line on completion.
"""

from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger("scout.access")

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
