"""Politeness layer: robots.txt + per-host rate limiting (plan 14).

Two concerns, two helpers:

  * :class:`RobotsCache` — fetches and caches ``robots.txt`` per host. Daily
    TTL (operator-friendly default; sources rarely change their robots
    policy intra-day). One concurrent fetch per host via an asyncio.Lock so
    we don't stampede on first use.

  * :class:`RateLimiter` — enforces a minimum delay between requests to the
    same host. Default 3s (overridable per-source via
    ``politeness_delay_seconds``). Implementation is a per-host async lock
    plus a "last fired" timestamp.

Both are designed as singletons within a crawler run. Construct one of each
at the top of :func:`crawl_source` and pass into the fetch loop.
"""

from __future__ import annotations

import asyncio
import time
import urllib.parse
from urllib.robotparser import RobotFileParser

import httpx
import structlog

log = structlog.get_logger("scout.scraper.politeness")

# RobotsCache TTL: 24 hours. Sources rarely change robots policy intra-day,
# and we'd rather pay the round-trip cost once than per-URL.
_ROBOTS_TTL_SECONDS = 86_400


class RobotsCache:
    """Per-host robots.txt cache.

    Public API:
      * :meth:`is_allowed` — returns True if the given URL is fetchable
        under the cached policy for its host. False on Disallow; True on
        404/permissive responses. The check is non-fatal — a missing
        ``robots.txt`` is interpreted as "everything allowed."

    Implementation notes:
      * RobotFileParser is sync; we run its parse step in-process (cheap).
      * The ``client`` argument lets us share the SSRF-guarded transport.
    """

    def __init__(self) -> None:
        # host -> (RobotFileParser, expires_at_monotonic)
        self._cache: dict[str, tuple[RobotFileParser, float]] = {}
        # host -> Lock to serialize concurrent first-fetches
        self._locks: dict[str, asyncio.Lock] = {}

    def _key(self, url: str) -> tuple[str, str]:
        parsed = urllib.parse.urlsplit(url)
        # robots.txt is per scheme+host(+port).
        host_key = parsed.netloc
        robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        return host_key, robots_url

    async def _fetch_robots(
        self, host_key: str, robots_url: str, client: httpx.AsyncClient
    ) -> RobotFileParser:
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            resp = await client.get(robots_url, timeout=10.0)
        except httpx.HTTPError as exc:
            log.info("scraper.robots_unreachable", host=host_key, error=str(exc))
            # Treat unreachable robots as "no policy" — RFC-permissive default.
            parser.parse([])
            return parser
        if resp.status_code == 404:
            log.info("scraper.robots_not_found", host=host_key)
            parser.parse([])
            return parser
        if resp.status_code >= 400:
            log.info(
                "scraper.robots_error",
                host=host_key,
                status=resp.status_code,
            )
            parser.parse([])
            return parser
        parser.parse(resp.text.splitlines())
        return parser

    async def is_allowed(
        self,
        url: str,
        user_agent: str,
        client: httpx.AsyncClient,
    ) -> bool:
        """Return True if ``user_agent`` may fetch ``url`` under cached robots.

        Caches the parsed RobotFileParser per host. First call per host within
        a TTL window pays the robots.txt round-trip; subsequent calls are
        sync.
        """
        host_key, robots_url = self._key(url)
        now = time.monotonic()
        cached = self._cache.get(host_key)
        if cached and cached[1] > now:
            return cached[0].can_fetch(user_agent, url)

        lock = self._locks.setdefault(host_key, asyncio.Lock())
        async with lock:
            # Re-check after waiting for the lock; another coroutine may
            # have populated the cache for us already.
            cached = self._cache.get(host_key)
            if cached and cached[1] > now:
                return cached[0].can_fetch(user_agent, url)
            parser = await self._fetch_robots(host_key, robots_url, client)
            self._cache[host_key] = (parser, now + _ROBOTS_TTL_SECONDS)
        return parser.can_fetch(user_agent, url)


class RateLimiter:
    """Per-host minimum-delay rate limiter.

    Each call to :meth:`acquire` blocks until at least ``delay_seconds``
    have elapsed since the previous acquire for the same host. Delays are
    set per-host via :meth:`set_delay` (called by the crawler before any
    request, using ``Source.politeness_delay_seconds``).

    Defaults to a 3-second baseline if a host hasn't had ``set_delay``
    called for it — defensive against accidental ``source_id`` misses.
    """

    def __init__(self, default_delay: float = 3.0) -> None:
        self._default_delay = default_delay
        # host -> delay seconds (float)
        self._delays: dict[str, float] = {}
        # host -> Lock to serialize "wait then go"
        self._locks: dict[str, asyncio.Lock] = {}
        # host -> last-acquired monotonic
        self._last: dict[str, float] = {}

    def set_delay(self, host: str, delay_seconds: float) -> None:
        if delay_seconds < 0:
            delay_seconds = 0
        self._delays[host] = delay_seconds

    async def acquire(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        delay = self._delays.get(host, self._default_delay)
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            wait = (last + delay) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()
