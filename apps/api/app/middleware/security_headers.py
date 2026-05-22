"""Browser security headers (plan 29).

Local-install posture: the api both serves the SPA and the JSON API on
the same origin, so CORS isn't a concern in production. What matters
here is hardening the browser's interpretation of the responses we send:

  * **CSP** — restrict script + style sources so a successful injection
    can't load a remote payload. We allow ``'self'`` for both, plus
    inline styles (Tailwind v4 ships small inline blocks the dev server
    occasionally emits). Inline scripts are forbidden — Vite's build
    output uses external module scripts only.
  * **X-Frame-Options: DENY** — prevent clickjacking by disallowing
    framing entirely. There's no legitimate framing use case here.
  * **X-Content-Type-Options: nosniff** — disable MIME-sniffing so an
    asset served as text/plain stays text/plain.
  * **Referrer-Policy: same-origin** — outbound link clicks shouldn't
    leak the local install's URL structure.
  * **Strict-Transport-Security** — only meaningful behind HTTPS, but
    sending it when behind a reverse proxy that adds TLS doesn't hurt.
    Conservative max-age (1 day) by default; production deployments
    behind a stable cert should bump via env override.
  * **Permissions-Policy** — opt out of every powerful browser API we
    don't use (camera, microphone, geolocation, etc.).

JSON API responses also get the headers — they're harmless there and a
single middleware is easier to reason about than two.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Request, Response

# CSP shipped on every response. ``style-src 'unsafe-inline'`` is here
# because Tailwind v4's vite plugin emits small inline style blocks for
# the dev server (production build is external CSS only, but we keep the
# directive uniform). ``connect-src 'self'`` covers SSE + fetch back to
# the api.
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

# Disable every powerful API. Add a directive back here if a future
# feature legitimately needs one.
_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)

# 1-day HSTS — non-zero so browsers remember the preference, short enough
# that a misconfigured TLS cert isn't a multi-month lockout.
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
