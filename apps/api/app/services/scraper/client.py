"""SSRF-guarded httpx.AsyncClient (plan 14).

The scraper makes outbound HTTP requests on behalf of configured sources.
Without an egress filter, a hostile or merely misconfigured source could
redirect us to ``127.0.0.1``, ``169.254.169.254`` (AWS metadata), or any
RFC1918 address — letting external content reach internal services. The
transport below resolves every URL's hostname before the request leaves
the process and rejects anything that resolves to a non-public address.

Two layers of defence:
  1. Pre-DNS allowlist via ``ipaddress.ip_address(...).is_global`` on the
     resolved address.
  2. ``follow_redirects=True`` on the underlying client — but we re-validate
     on each redirect target via the same transport.

The client is also branded with the Scout User-Agent so source operators can
trace requests back to us (and ban us if they want — robots.txt support also
respects per-source ``Disallow`` rules).
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Final

import httpx
import structlog

from app.settings import get_settings

log = structlog.get_logger("scout.scraper.client")

# Default timeouts. Conservative — most conference websites are fast.
DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(15.0, connect=8.0)


class SSRFProtectionError(httpx.HTTPError):
    """Raised when a target hostname resolves to a non-public address."""


def _is_public_address(host: str) -> bool:
    """Resolve ``host`` and confirm at least one resolution is public.

    DNS may return multiple A/AAAA records. We reject the host if ANY of
    them is private/loopback/link-local — a defender's choice: better to
    over-block than to leak.

    Bare IPs are checked directly (``getaddrinfo`` happily returns them
    in the resolution list).
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Let httpx fail with its own "could not resolve" error. We're not
        # the right layer to surface DNS failures.
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if not ip.is_global:
            return False
    return True


class _SSRFGuardedTransport(httpx.AsyncHTTPTransport):
    """httpx transport that rejects requests to non-public IPs.

    Implemented at the transport layer so it runs after redirect resolution
    — every redirect target goes through ``handle_async_request`` and the
    check fires anew.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not _is_public_address(host):
            log.warning("scraper.ssrf_blocked", url=str(request.url))
            raise SSRFProtectionError(
                f"Refusing to send request to non-public host {host!r}. "
                "Scraper only contacts public-internet addresses."
            )
        return await super().handle_async_request(request)


def make_async_client(
    *,
    timeout: httpx.Timeout | float | None = None,
    user_agent: str | None = None,
) -> httpx.AsyncClient:
    """Construct an SSRF-guarded httpx.AsyncClient.

    Callers should use ``async with make_async_client() as client:`` to ensure
    the transport is closed cleanly. Pass per-call overrides via ``timeout``
    or ``user_agent``; default UA comes from ``settings.scraper_user_agent``.
    """
    settings = get_settings()
    return httpx.AsyncClient(
        transport=_SSRFGuardedTransport(),
        timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": user_agent or settings.scraper_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/rss+xml;q=0.9,application/atom+xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.9",
        },
        # No cookies by default — sources should be public, no session needed.
        # Limits: 5 simultaneous connections is plenty for a one-source crawl;
        # the per-host politeness gate is the real concurrency knob.
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    )
