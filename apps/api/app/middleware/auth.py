"""Auth middleware.

Reads the authenticated user's email from the ``X-Auth-Request-Email`` header
injected by the openshift/oauth-proxy sidecar. In local dev (no sidecar),
falls back to the ``SCOUT_DEV_USER_EMAIL`` environment variable so the
rest of the app never has to branch on environment.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
