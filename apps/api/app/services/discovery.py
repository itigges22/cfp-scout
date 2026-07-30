"""Finding conferences on the open web, and fetching the pages.

WHAT THIS DOES
    Everything between "we have some keywords" and "we have a RawPage row
    to extract from", in one place.

        politeness  robots.txt cache and a per-host rate limiter
        client      the shared async HTTP client, with SSRF protection
        storage     hash the body, write it to the raw-page volume
        fetch       one URL: robots check, conditional GET, save
        discovery   pull candidate URLs out of a curated Source
        crawl       run a whole Source and report what happened
        search      keyword -> queries -> provider results
        crawler     render a found page and pull conference links out
        feeds       curated feeds as a second, non-search channel
        orchestrate the deep sweep that drives all of the above

HOW IT CONNECTS
    Called by   tasks.py, tasks.py,
                api/v1/admin_discovery.py
    Writes      raw_pages and the raw-page volume; conference rows via
                services/extraction.py
    Reads       sources, and the operator's keyword list from settings
    Downstream  services/extraction.py turns each RawPage into a Conference

    Curated Sources are the other half of the input: an operator can
    name a site to watch instead of relying on search alone. Their CRUD
    lives here because a Source exists only to be crawled.

WORTH KNOWING
    These were two packages and ten modules with SIXTEEN cross-references
    between them — politeness, client, storage and fetch existed only to
    be called by the crawl three files away, and the orchestrator reached
    across the package boundary for half of them. Following one discovery
    run meant ten files.

    The sweep must be exhaustive, not a first page of results: it expands
    the operator's handful of keywords into many queries, runs several
    channels (search, curated feeds, link crawling), and keeps going until
    the channels stop yielding anything new.

    Dedup happens on EVERY call, against the running found-set, so the same
    conference discovered through three channels is appended once.

    Two different things were both called ``SourceCrawlStats``: run statistics
    for one source, and one fetched page. They are now ``SourceCrawlStats``
    and ``CrawledPage``.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import socket
import time
import urllib.parse
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser
from uuid import UUID

import feedparser
import httpx
import structlog
from fastapi import HTTPException, status
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conference, RawPage, Source
from app.scheduler import enqueue_task
from app.schemas import Page, SourceCreate, SourceRead, SourceUpdate
from app.services.conferences import conference_embed_text
from app.services.embeddings import embed_owner
from app.services.extraction import build_slug, find_duplicate, parse_raw_page, year_for
from app.services.records import model_to_audit_dict, paginate, write_audit
from app.settings import get_settings

log = structlog.get_logger("scout.discovery")


# ==========================================================================
# discovery.py
# ==========================================================================




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
            self._cache[host_key] = (parser, now + get_settings().discovery_robots_ttl_seconds)
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


DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(15.0, connect=8.0)


class SSRFProtectionError(httpx.HTTPError):
    """Raised when a target hostname resolves to a non-public address."""


def is_public_url(url: str) -> bool:
    """Would fetching ``url`` reach a public address?

    The public entry point for callers that do NOT fetch through httpx and
    so cannot use the guarded transport below. services/web_discovery
    hands URLs to Crawl4AI's headless browser, which owns its own network
    stack — and those URLs come from search-engine results and links mined
    off aggregator pages, both of which an outsider can influence. Without
    a check there, discovery is a request-forgery primitive pointed at
    whatever the crawler is asked to visit.

    WEAKER THAN THE TRANSPORT GUARD, deliberately and unavoidably. This
    resolves the hostname before the fetch, so it cannot see a redirect to
    a private address the way _SSRFGuardedTransport can, and a name that
    changes its answer between this call and the fetch defeats it. It is a
    pre-flight screen, not a guarantee. Where httpx is doing the fetching,
    use make_async_client instead.
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    return _is_public_address(host)


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


def _raw_pages_root() -> Path:
    settings = get_settings()
    return Path(settings.storage_path) / "raw_pages"


def compute_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def save_raw_body(source_id: UUID, body: bytes, sha256: str) -> Path:
    """Write ``body`` to disk under the source's directory. Idempotent —
    re-saving the same bytes is a no-op.

    Returns the absolute path the body landed at (for ``raw_pages.raw_body_path``).
    """
    root = _raw_pages_root() / str(source_id)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{sha256}.html"
    if target.exists():
        return target
    target.write_bytes(body)
    target.chmod(0o640)
    return target




MAX_BODY_BYTES = 5 * 1024 * 1024


@dataclass(slots=True, frozen=True)
class FetchOutcome:
    """Result of a single-URL fetch."""

    url: str
    status: str  # "fetched" / "deduped" / "skipped_robots" / "skipped_304" / "error" / "js_blocked"
    http_status: int | None = None
    raw_page_id: UUID | None = None
    error: str | None = None

    @classmethod
    def error_outcome(cls, url: str, error: str) -> FetchOutcome:
        return cls(url=url, status="error", error=error)


async def fetch_one(
    *,
    db: AsyncSession,
    source_id: UUID,
    url: str,
    user_agent: str,
    client: httpx.AsyncClient,
    robots: RobotsCache,
    rate_limit: RateLimiter,
) -> FetchOutcome:
    """Fetch + persist a single URL.

    All policy decisions (robots, rate limit, conditional GET, dedup) live
    inside this function — the caller just hands over the URL and the
    helpers.
    """
    bound = log.bind(scrape_url=url, source_id=str(source_id))

    try:
        allowed = await robots.is_allowed(url, user_agent, client)
    except Exception as exc:
        bound.warning("scraper.robots_check_failed", error=str(exc))
        allowed = True
    if not allowed:
        bound.info("scraper.skipped_robots")
        return FetchOutcome(url=url, status="skipped_robots")

    await rate_limit.acquire(url)

    # Conditional GET: if we've already fetched this URL, send the prior
    # ETag/Last-Modified so the server can answer 304 cheaply.
    prior = await _find_prior_fetch(db, source_id, url)
    headers: dict[str, str] = {}
    if prior:
        if prior.etag:
            headers["If-None-Match"] = prior.etag
        if prior.last_modified:
            headers["If-Modified-Since"] = prior.last_modified

    try:
        resp = await client.get(url, headers=headers)
    except SSRFProtectionError as exc:
        # Caught by name, BEFORE the generic handler. SSRFProtectionError
        # subclasses httpx.HTTPError, so it used to be swallowed below and
        # reported as an ordinary fetch failure — a blocked request to an
        # internal address looked identical to a timeout in ingest_jobs, and
        # the only evidence was one log line.
        bound.warning("scraper.ssrf_blocked", url=url, error=str(exc))
        return FetchOutcome.error_outcome(url, f"blocked (SSRF guard): {exc}")
    except httpx.HTTPError as exc:
        bound.warning("scraper.fetch_failed", error=str(exc))
        return FetchOutcome.error_outcome(url, str(exc))

    if resp.status_code == 304:
        bound.info("scraper.not_modified")
        return FetchOutcome(url=url, status="skipped_304", http_status=304)

    if resp.status_code >= 400:
        bound.info("scraper.http_error", http_status=resp.status_code)
        return FetchOutcome(
            url=url,
            status="error",
            http_status=resp.status_code,
            error=f"HTTP {resp.status_code}",
        )

    body = resp.content
    if len(body) > MAX_BODY_BYTES:
        bound.warning("scraper.body_too_large", bytes=len(body))
        return FetchOutcome(
            url=url,
            status="error",
            http_status=resp.status_code,
            error=f"body too large ({len(body)} bytes; cap {MAX_BODY_BYTES})",
        )

    sha = compute_sha256(body)

    # Dedup by content hash (cross-URL): the unique constraint on raw_pages.hash
    # would reject the insert anyway, but checking up front lets us update
    # fetched_at on the existing row and return a clean ``deduped`` outcome.
    existing = await _find_by_hash(db, sha)
    if existing is not None:
        existing.fetched_at = datetime.now(tz=UTC)
        await db.flush()
        bound.info("scraper.deduped", existing_raw_page_id=str(existing.id))
        return FetchOutcome(
            url=url,
            status="deduped",
            http_status=resp.status_code,
            raw_page_id=existing.id,
        )

    # Persist to disk + insert metadata row.
    storage_path = save_raw_body(source_id, body, sha)

    text_len = _approx_text_length(body, resp.headers.get("content-type", ""))
    parse_status = "needs_js_render" if text_len < get_settings().discovery_js_render_threshold else None

    row = RawPage(
        source_id=source_id,
        url=url,
        fetched_at=datetime.now(tz=UTC),
        http_status=resp.status_code,
        content_type=resp.headers.get("content-type", "application/octet-stream")[:120],
        raw_body_path=str(storage_path),
        hash=sha,
        etag=resp.headers.get("etag"),
        last_modified=resp.headers.get("last-modified"),
        parse_status=parse_status,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row, attribute_names=["id"])
    bound.info(
        "scraper.fetched",
        bytes=len(body),
        sha256=sha[:12],
        parse_status=parse_status,
    )
    return FetchOutcome(
        url=url,
        status="js_blocked" if parse_status == "needs_js_render" else "fetched",
        http_status=resp.status_code,
        raw_page_id=row.id,
    )


async def _find_prior_fetch(db: AsyncSession, source_id: UUID, url: str) -> RawPage | None:
    """Most-recent raw_pages row for (source, url) — drives conditional GET."""
    result = await db.execute(
        select(RawPage)
        .where(RawPage.source_id == source_id, RawPage.url == url)
        .order_by(RawPage.fetched_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _find_by_hash(db: AsyncSession, sha256: str) -> RawPage | None:
    result = await db.execute(select(RawPage).where(RawPage.hash == sha256))
    return result.scalar_one_or_none()


def _approx_text_length(body: bytes, content_type: str) -> int:
    """Rough text-content length for the JS-render heuristic.

    For HTML, strip tags via selectolax. For non-HTML, return raw length —
    the heuristic doesn't really apply (RSS/JSON aren't expected to need
    JS to render).
    """
    if "html" not in content_type.lower():
        return len(body)
    try:
        from selectolax.lexbor import LexborHTMLParser

        parser = LexborHTMLParser(body.decode("utf-8", errors="replace"))
        text = parser.body.text(separator=" ", strip=True) if parser.body else ""
        return len(text)
    except Exception:
        return len(body)




async def discover_urls(
    *,
    kind: str,
    url: str,
    client: httpx.AsyncClient,
) -> list[str]:
    """Dispatch on ``kind`` and return candidate URLs, capped by the
    ``discovery_max_urls_per_source`` setting.

    THE CAP HAS NO CURSOR. Both paths below take the first N in feed or DOM
    order on every run, so a link past the cap is never fetched at all — it
    is not deferred to the next pass. For an rss source that is survivable
    (feeds rotate newest-first); for a page source with a stable link order
    it is a permanent recall ceiling.

    The fetch policy for the discovery request itself is the same as for
    target URLs — robots + rate-limit applied by the caller, never here.
    """
    # Skip pseudo-sources that exist only as bookkeeping markers (the web
    # discovery orchestrator inserts a "internal://web-discovery" Source
    # row so its raw_pages have something to FK to). httpx errors out on
    # non-http(s) schemes; we'd just be filling /diagnostics with junk.
    if not (url.startswith("http://") or url.startswith("https://")):
        log.info("scraper.discovery.skip_non_http", url=url, kind=kind)
        return []

    if kind == "rss":
        return await _discover_rss(url, client)
    if kind == "page":
        return await _discover_page(url, client)
    # Pass-2 kinds shouldn't reach here — the schema rejects them on create.
    raise ValueError(f"Unsupported source kind for pass 1: {kind!r}")


async def _discover_rss(url: str, client: httpx.AsyncClient) -> list[str]:
    resp = await client.get(url)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    urls: list[str] = []
    for entry in feed.entries:
        link = getattr(entry, "link", None)
        if not link:
            continue
        link = _absolutize(link, url)
        if link and link not in urls:
            urls.append(link)
        if len(urls) >= get_settings().discovery_max_urls_per_source:
            break
    log.info("scraper.discovery.rss", source_url=url, entries=len(feed.entries), yielded=len(urls))
    return urls


async def _discover_page(url: str, client: httpx.AsyncClient) -> list[str]:
    resp = await client.get(url)
    resp.raise_for_status()
    parser = LexborHTMLParser(resp.text)

    # Same-host filter — without this, "page" sources turn into uncontrolled
    # link-spiders that follow off-site URLs forever.
    base_host = urllib.parse.urlsplit(url).netloc.lower()
    out: list[str] = []
    seen: set[str] = set()
    for a in parser.css("a[href]"):
        href = a.attributes.get("href")
        if not href:
            continue
        absolute = _absolutize(href, url)
        if not absolute:
            continue
        host = urllib.parse.urlsplit(absolute).netloc.lower()
        if host != base_host:
            continue
        # Drop anchors, mailto:, javascript:, etc. (filtered by scheme)
        scheme = urllib.parse.urlsplit(absolute).scheme.lower()
        if scheme not in {"http", "https"}:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
        if len(out) >= get_settings().discovery_max_urls_per_source:
            break
    log.info("scraper.discovery.page", source_url=url, yielded=len(out))
    return out


def _absolutize(href: str, base: str) -> str | None:
    href = (href or "").strip()
    if not href:
        return None
    try:
        return urllib.parse.urljoin(base, href)
    except ValueError:
        return None


class SourceNotFoundError(LookupError):
    """Raised when ``crawl_source`` can't find the source row."""


class SourceDisabledError(RuntimeError):
    """Raised when the source row exists but ``enabled=false``."""


@dataclass(slots=True)
class SourceCrawlStats:
    """Aggregated outcome of a crawl run for one source.

    Serializable via ``asdict`` so the task runner can drop it into
    ``ingest_jobs.stats``.
    """

    source_id: str
    source_name: str
    pages_discovered: int = 0
    pages_fetched: int = 0
    pages_deduped: int = 0
    pages_skipped_robots: int = 0
    pages_skipped_304: int = 0
    pages_js_blocked: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_stats(self) -> dict:
        return asdict(self)


async def crawl_source(db: AsyncSession, source_id: UUID) -> SourceCrawlStats:
    """Run a full crawl for ``source_id`` and return aggregated stats."""
    source = await db.get(Source, source_id)
    if source is None:
        raise SourceNotFoundError(f"No source {source_id!s}")
    if not source.enabled:
        raise SourceDisabledError(f"Source {source.name!r} ({source.id}) is disabled.")

    bound = log.bind(source_id=str(source.id), source_name=source.name, kind=source.kind)
    bound.info("scraper.crawl.start", url=source.url)

    settings = get_settings()
    result = SourceCrawlStats(source_id=str(source.id), source_name=source.name)

    robots = RobotsCache()
    rate_limit = RateLimiter()
    # Set per-host delay from the source's configured politeness.
    import urllib.parse

    host = urllib.parse.urlsplit(source.url).netloc
    rate_limit.set_delay(host, source.politeness_delay_seconds)

    async with make_async_client(user_agent=settings.scraper_user_agent) as client:
        try:
            candidate_urls = await discover_urls(kind=source.kind, url=source.url, client=client)
        except Exception as exc:
            bound.error("scraper.discovery_failed", error=str(exc))
            raise

        result.pages_discovered = len(candidate_urls)
        bound.info("scraper.crawl.discovered", count=len(candidate_urls))

        # IDs of raw_pages we'll enqueue for extraction after the
        # crawl finishes. Collect now, dispatch later — APScheduler add_job
        # is fast but doing it inside the per-URL await would slow the
        # loop without benefit.
        new_raw_page_ids: list[str] = []

        for url in candidate_urls:
            outcome = await fetch_one(
                db=db,
                source_id=source.id,
                url=url,
                user_agent=settings.scraper_user_agent,
                client=client,
                robots=robots,
                rate_limit=rate_limit,
            )
            if outcome.status == "fetched":
                result.pages_fetched += 1
                if outcome.raw_page_id is not None:
                    new_raw_page_ids.append(str(outcome.raw_page_id))
            elif outcome.status == "deduped":
                result.pages_deduped += 1
            elif outcome.status == "skipped_robots":
                result.pages_skipped_robots += 1
            elif outcome.status == "skipped_304":
                result.pages_skipped_304 += 1
            elif outcome.status == "js_blocked":
                result.pages_js_blocked += 1
                # JS-blocked pages still got persisted; we explicitly skip
                # extraction since the body is unlikely to yield anything
                # useful to the LLM.
            elif outcome.status == "error":
                result.errors.append(
                    {
                        "url": outcome.url,
                        "http_status": outcome.http_status,
                        "error": outcome.error,
                    }
                )

    source.last_crawled_at = datetime.now(tz=UTC)
    await db.flush()

    # Enqueue extraction for each newly-fetched raw_page. Local
    # import keeps the scraper package free of a circular dep on the tasks
    # package (which itself imports the scheduler).
    if new_raw_page_ids:

        for rp_id in new_raw_page_ids:
            enqueue_task(
                "parse_raw_page",
                job_id=f"parse-{rp_id}",
                kwargs={"raw_page_id": rp_id},
            )
        bound.info("scraper.crawl.parse_enqueued", count=len(new_raw_page_ids))

    bound.info("scraper.crawl.done", **result.to_stats() | {"errors": len(result.errors)})
    return result


SearchProvider = Literal["ddg", "brave", "tavily"]


class SearchError(RuntimeError):
    """Any provider-level failure (quota, auth, network)."""


@dataclass(slots=True, frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    score: float | None = None  # provider-supplied relevance; None for DDG


async def web_search(
    *,
    prompt: str,
    provider: SearchProvider,
    max_results: int,
    brave_api_key: str | None = None,
    tavily_api_key: str | None = None,
) -> list[SearchHit]:
    """Run a search against the chosen provider. Returns up to
    ``max_results`` hits in provider order (already deduped on URL)."""
    if not prompt.strip():
        return []

    log.info("discovery.search.begin", provider=provider, prompt_chars=len(prompt))

    if provider == "ddg":
        hits = await _search_ddg(prompt, max_results)
    elif provider == "brave":
        if not brave_api_key:
            raise SearchError("Brave search selected but discovery_brave_api_key is not set")
        hits = await _search_brave(prompt, max_results, brave_api_key)
    elif provider == "tavily":
        if not tavily_api_key:
            raise SearchError("Tavily search selected but discovery_tavily_api_key is not set")
        hits = await _search_tavily(prompt, max_results, tavily_api_key)
    else:  # pragma: no cover — Literal exhausted
        raise SearchError(f"unknown search provider: {provider}")

    seen: set[str] = set()
    unique: list[SearchHit] = []
    for h in hits:
        if h.url in seen:
            continue
        seen.add(h.url)
        unique.append(h)
    log.info("discovery.search.done", provider=provider, results=len(unique))
    return unique


def build_queries(
    *,
    keywords: Sequence[str],
    templates: Sequence[str],
    years: Sequence[int],
) -> list[str]:
    """Expand the operator's keywords into the full query set.

    One keyword is not one search. ``"AI"`` searched once returns the same
    twenty pages every run; ``"AI"`` crossed with four phrasings and two
    years returns eight different result sets, and the union is what makes
    the sweep deep rather than wide-ish.

    Templates that mention neither placeholder are passed through once
    rather than repeated per keyword — that lets an operator add a
    standalone query without it being multiplied.
    """
    seen: set[str] = set()
    out: list[str] = []
    for template in templates:
        has_kw = "{keyword}" in template
        has_year = "{year}" in template
        # A template with no placeholders is a literal query, not a shape.
        kw_values = keywords if has_kw else [""]
        year_values = years if has_year else [0]
        for kw in kw_values:
            if has_kw and not kw.strip():
                continue
            for yr in year_values:
                q = template.replace("{keyword}", kw.strip()).replace("{year}", str(yr))
                q = " ".join(q.split())
                if q and q not in seen:
                    seen.add(q)
                    out.append(q)
    return out


async def web_search_many(
    *,
    queries: Sequence[str],
    provider: SearchProvider,
    max_results_per_query: int,
    brave_api_key: str | None = None,
    tavily_api_key: str | None = None,
    max_concurrency: int = 4,
) -> list[SearchHit]:
    """Run every query and return the deduplicated union of their hits.

    Two properties matter more than speed here, both in service of recall:

    A failing query must not fail the run. Providers rate-limit, CAPTCHA
    and time out unpredictably — DDG especially. One bad query returning
    nothing should cost its own results and no others, so each is caught
    individually and logged.

    Order is first-seen. The first query to surface a URL wins it, so the
    earlier (more specific) phrasings shape the head of the list, and
    later ones only contribute what nothing before them found.
    """
    if not queries:
        return []

    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def _one(q: str) -> list[SearchHit]:
        async with sem:
            try:
                return await web_search(
                    prompt=q,
                    provider=provider,
                    max_results=max_results_per_query,
                    brave_api_key=brave_api_key,
                    tavily_api_key=tavily_api_key,
                )
            except Exception as exc:
                # Deliberately broad: a provider can fail in as many ways as
                # the internet has failure modes, and none of them justify
                # abandoning the other queries.
                log.warning(
                    "discovery.search.query_failed",
                    query=q[:120],
                    provider=provider,
                    error=str(exc)[:200],
                )
                return []

    batches = await asyncio.gather(*(_one(q) for q in queries))

    seen: set[str] = set()
    unique: list[SearchHit] = []
    for batch in batches:
        for h in batch:
            if h.url in seen:
                continue
            seen.add(h.url)
            unique.append(h)

    failed = sum(1 for b in batches if not b)
    log.info(
        "discovery.search.sweep_done",
        provider=provider,
        queries=len(queries),
        empty_queries=failed,
        unique_urls=len(unique),
    )
    return unique


async def _search_ddg(prompt: str, max_results: int) -> list[SearchHit]:
    """Wraps ``ddgs.DDGS`` in a threadpool — DDGS is sync and the library
    doesn't ship an async API yet.

    DDG is *aggressively* rate-limited: empty result pages and CAPTCHA
    fallbacks happen mid-stream. We retry with exponential backoff up
    to 3 times. If the prompt is >120 chars the search box also tends
    to return nothing, so we fall back to a truncated version on the
    second attempt.
    """
    import asyncio

    from anyio import to_thread

    def _run(query: str) -> list[SearchHit]:
        # Local import — ddgs has a noisy import path that we don't want
        # at module-level (slow startup).
        from ddgs import DDGS

        hits: list[SearchHit] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                if not r or not r.get("href"):
                    continue
                hits.append(
                    SearchHit(
                        url=str(r["href"]),
                        title=str(r.get("title") or ""),
                        snippet=str(r.get("body") or ""),
                    )
                )
        return hits

    # Three attempts: full prompt, then a shorter version (first 8 words)
    # which DDG handles much more reliably, then full prompt again.
    short_prompt = " ".join(prompt.split()[:8])
    attempts: list[tuple[str, float]] = [
        (prompt, 0.0),
        (short_prompt, 2.0),
        (prompt, 5.0),
    ]
    last_error: Exception | None = None
    for query, delay in attempts:
        if delay:
            await asyncio.sleep(delay)
        try:
            hits = await to_thread.run_sync(lambda q=query: _run(q))
            if hits:
                return hits
            log.info(
                "discovery.search.ddg.retry_empty",
                query_chars=len(query),
                used_short=(query == short_prompt),
            )
        except Exception as exc:
            log.warning(
                "discovery.search.ddg.attempt_failed",
                error=str(exc)[:200],
                query_chars=len(query),
            )
            last_error = exc

    if last_error is not None:
        raise SearchError(f"DuckDuckGo search failed: {last_error}") from last_error
    return []


async def _search_brave(prompt: str, max_results: int, api_key: str) -> list[SearchHit]:
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": prompt, "count": min(max_results, 20)}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        body = r.json()
    except httpx.HTTPError as exc:
        raise SearchError(f"Brave search HTTP error: {exc}") from exc

    web = (body or {}).get("web", {}) or {}
    results = web.get("results") or []
    return [
        SearchHit(
            url=str(item.get("url") or ""),
            title=str(item.get("title") or ""),
            snippet=str(item.get("description") or ""),
        )
        for item in results
        if item.get("url")
    ]


async def _search_tavily(prompt: str, max_results: int, api_key: str) -> list[SearchHit]:
    url = "https://api.tavily.com/search"
    body = {
        "api_key": api_key,
        "query": prompt,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, json=body)
        r.raise_for_status()
        payload = r.json()
    except httpx.HTTPError as exc:
        raise SearchError(f"Tavily search HTTP error: {exc}") from exc

    results = (payload or {}).get("results") or []
    return [
        SearchHit(
            url=str(item.get("url") or ""),
            title=str(item.get("title") or ""),
            snippet=str(item.get("content") or ""),
            score=float(item.get("score")) if item.get("score") is not None else None,
        )
        for item in results
        if item.get("url")
    ]


@dataclass(slots=True, frozen=True)
class CrawledPage:
    url: str
    final_url: str  # post-redirect
    status_code: int
    markdown: str
    raw_html_bytes: int
    title: str | None


class CrawlError(RuntimeError):
    """Surfaced when Crawl4AI fails for a given URL."""




async def crawl_many(urls: list[str]) -> list[CrawledPage]:
    """Fetch all ``urls`` in a single Crawl4AI session.

    Crawl4AI under the hood does an async concurrent fetch; we let it
    handle its own concurrency. We do still wrap each per-URL run in a
    timeout so a slow site can't hold up the discovery run.
    """
    if not urls:
        return []

    # Local import — pulls in heavy ML deps (tokenizers, etc.). Keeping
    # it out of module-level keeps unrelated routes' import time fast.
    # AsyncHTTPCrawlerStrategy avoids the Playwright/Chromium dependency
    # (saves ~250 MB image + a separate `playwright install` step). The
    # PRD's "potentially utilize Playwright for JS-heavy sites" is a
    # future enhancement.
    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]
        from crawl4ai.async_crawler_strategy import (  # type: ignore[import-not-found]
            AsyncHTTPCrawlerStrategy,
        )
    except ImportError as exc:
        raise CrawlError(
            "crawl4ai is not installed; rebuild the api image after pyproject.toml is updated"
        ) from exc

    out: list[CrawledPage] = []
    log.info("discovery.crawl.begin", url_count=len(urls))

    async with AsyncWebCrawler(
        crawler_strategy=AsyncHTTPCrawlerStrategy(),
        verbose=False,
    ) as crawler:
        for url in urls:
            try:
                async with asyncio.timeout(get_settings().discovery_per_url_timeout_seconds):
                    raw = await crawler.arun(url=url)
            except (TimeoutError, Exception) as exc:
                log.warning(
                    "discovery.crawl.failed",
                    url=url,
                    error=str(exc)[:200],
                    error_type=type(exc).__name__,
                )
                continue

            md = getattr(raw, "markdown", None) or ""
            html_bytes = len((getattr(raw, "html", None) or "").encode("utf-8"))
            status_code = int(getattr(raw, "status_code", 0) or 0)
            # Crawl4AI's metadata can be missing, None, or a dict. Defend
            # against all three — the getattr-default trick fails when
            # the attribute exists but is None.
            meta = getattr(raw, "metadata", None) or {}
            title = meta.get("title") if isinstance(meta, dict) else None

            out.append(
                CrawledPage(
                    url=url,
                    final_url=str(getattr(raw, "url", url) or url),
                    status_code=status_code,
                    markdown=str(md),
                    raw_html_bytes=html_bytes,
                    title=str(title) if title else None,
                )
            )
            log.info(
                "discovery.crawl.fetched",
                url=url,
                status=status_code,
                md_chars=len(md),
            )

    log.info("discovery.crawl.done", successes=len(out), attempted=len(urls))
    return out


_MD_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")


_CONFERENCE_LIKE_KEYWORDS = (
    # CFP / submission markers
    "cfp",
    "call-for-papers",
    "call_for_papers",
    "callforpapers",
    "call-for-speakers",
    "call-for-proposals",
    "speakers",
    "submit",
    "submissions",
    "speaker-application",
    "speaker-form",
    "sponsor",
    "sponsorship",
    # Event-type markers
    "conference",
    "symposium",
    "workshop",
    "summit",
    "convention",
    "meetup",
    "hackathon",
    "ai-event",
    "ai_event",
    "/event",
    "/events/",
    "/talks/",
    "fireside",
    "panel",
    "demoday",
    "demo-day",
    "festival",
    # Famous AI/ML venues (academic + industry)
    "neurips",
    "icml",
    "iclr",
    "aaai",
    "ijcai",
    "kdd",
    "acl",
    "emnlp",
    "naacl",
    "wsdm",
    "www",
    "sigir",
    "cikm",
    "cvpr",
    "iccv",
    "eccv",
    "mlsys",
    "aied",
    "uist",
    # Year segments — 2026 / 2027 / 2028
    "/2026",
    "/2027",
    "/2028",
)


def extract_conference_links(
    markdown: str,
    *,
    source_url: str,
    blocklist_substrings: list[str] | None = None,
    max_links: int = 50,
) -> list[str]:
    """Pull URLs from ``markdown`` that look like individual conference
    pages — used to expand an aggregator (aideadlin.es / papercall.io)
    into individual crawl candidates.

    Filter pipeline (in order):
      1. Must be absolute http(s) URL.
      2. Drop fragment + trailing slash for dedup.
      3. Skip same as source_url.
      4. Skip if it matches the operator blocklist, or looks like site
         furniture (login, privacy, a PDF, …).
      5. PRIORITISE conference-like URLs, but do not require them.
      6. Cap to ``max_links``, hinted links first.

    Step 5 used to be a hard filter, and it was expensive. Measured against
    fifteen real conference URLs it rejected seven: JavaZone, GopherCon,
    Devoxx, QCon London, AI Engineer, KCD Texas and a Sessionize listing.
    The reason is structural rather than a gap in the word list — an
    established conference usually lives on a domain named after itself
    (``gophercon.com``), so there is no "conference-like" token in the URL
    to match, and no amount of adding words fixes that.

    Recall is the objective (W1), and the expensive filters now sit
    downstream where they can read the page instead of guessing from the
    URL: extraction scores its own confidence and quarantines what it
    cannot parse, and the LLM judge sees every conference. So the hint
    list keeps its real job — deciding what to spend the crawl budget on
    FIRST — and loses the job it was bad at, deciding what to discard.
    """
    blocklist = [b.lower() for b in (blocklist_substrings or []) if b]
    hinted: list[str] = []
    other: list[str] = []
    seen: set[str] = set()
    src_norm = _normalize(source_url)

    for raw_url in _MD_LINK_RE.findall(markdown or ""):
        url = urljoin(source_url, raw_url)
        url, _ = urldefrag(url)
        url = url.rstrip("/")
        if not url or url == src_norm or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        u_lower = url.lower()
        if any(b in u_lower for b in blocklist):
            continue
        if _is_site_furniture(u_lower):
            continue
        seen.add(url)
        if any(kw in u_lower for kw in _CONFERENCE_LIKE_KEYWORDS):
            hinted.append(url)
        else:
            other.append(url)

    candidates = (hinted + other)[:max_links]

    log.info(
        "discovery.crawl.link_extract",
        source_url=source_url,
        markdown_chars=len(markdown or ""),
        hinted=len(hinted),
        unhinted=len(other),
        candidates=len(candidates),
        # If this is nonzero the seed had more to give than the budget
        # allowed — raise discovery_max_links_per_seed rather than assume
        # the aggregator was exhausted.
        truncated=max(0, len(hinted) + len(other) - max_links),
    )
    return candidates


_SITE_FURNITURE = (
    "/login", "/signin", "/sign-in", "/signup", "/sign-up", "/register?",
    "/account", "/profile", "/settings", "/privacy", "/terms", "/legal",
    "/cookie", "/contact", "/about-us", "/careers", "/jobs", "/press",
    "/rss", "/feed.xml", "/sitemap", "/search?", "/tag/", "/category/",
    "/docs/", "/documentation", "/api/", "/pricing", "/download",
)


_BINARY_SUFFIXES = (
    ".pdf", ".zip", ".tar", ".gz", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".mp4", ".mp3", ".css", ".js", ".ics", ".xml", ".json",
)


def _is_site_furniture(u_lower: str) -> bool:
    """True for links that are part of a website rather than an event."""
    if u_lower.endswith(_BINARY_SUFFIXES):
        return True
    return any(f in u_lower for f in _SITE_FURNITURE)


def _normalize(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


DEVELOPERS_EVENTS_URL = "https://developers.events/all-events.json"


@dataclass(slots=True)
class FeedIngestResult:
    """Returned by :func:`ingest_developers_events`."""

    source: str
    total_in_feed: int
    matched_filter: int  # passed keyword + future-date filters
    new_conferences: int
    updated_conferences: int
    skipped_duplicate: int
    errors: int
    #: Future-dated events the keyword filter rejected. Reported so the
    #: cost of filtering is visible: measured against the live feed this
    #: was 375 of 801 future events, including KeyCloakCon, ArgoCon and
    #: Open Source Summit Korea. A filter whose losses nobody counts looks
    #: free.
    dropped_by_keyword_filter: int = 0
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class FeedFilters:
    #: Off by default, deliberately.
    #:
    #: This filter existed to keep feed volume down. Measured against the
    #: live developers.events feed there is no volume to keep down: 5,996
    #: events, of which only 801 are future-dated — a trivial number of
    #: rows. What the filter actually did was drop 375 of those 801,
    #: among them conferences for the team's own projects.
    #:
    #: Recall is the objective (W1). An event nobody was shown is
    #: invisible forever; an irrelevant one costs a single click to
    #: reject, and the matcher ranks it to the bottom anyway. Leave this
    #: off unless the feed genuinely floods the list.
    only_ai: bool = False
    future_only: bool = True
    limit: int | None = None
    # When set, only ingest events with status in this set (feed uses
    # 'open' / 'past' / 'cancelled').
    only_status: set[str] = field(
        default_factory=lambda: {"open"}
    )


_AI_KEYWORDS = {
    # Core
    "ai", "ml", "machine learning", "machinelearning",
    "deep learning", "deeplearning", "neural", "neural network",
    "data", "datascience", "data science", "data engineering",
    "big data", "data ops", "dataops",
    # LLM / GenAI ecosystem
    "llm", "llms", "gpt", "genai", "generative ai", "generative",
    "agent", "agents", "agentic", "rag", "retrieval-augmented",
    "embedding", "embeddings", "vector", "vector db", "vector search",
    "fine-tune", "fine-tuning", "finetune", "finetuning",
    "transformer", "transformers", "diffusion", "synthetic data",
    "prompt", "prompting", "prompt engineering", "context engineering",
    "tokenizer", "tokenization",
    # Modalities
    "nlp", "natural language", "computer vision", "vision", "speech",
    "asr", "tts", "audio", "video", "multimodal",
    "robotics", "reinforcement", "rl",
    # Platforms / tooling
    "mlops", "ml ops", "llmops", "ml platform", "model serving",
    "inference", "training", "evaluation", "evals", "benchmark",
    "huggingface", "hugging face", "pytorch", "tensorflow", "jax",
    "openai", "anthropic", "claude", "gemini", "llama", "mistral",
    # Adjacent
    "ai safety", "alignment", "interpretability", "trust", "responsible ai",
    "ethics", "fairness", "bias",
    "kubeflow", "kserve", "ray", "vllm", "ollama",
    "mlflow", "wandb", "weights & biases",
    # Event-type signals (so a generic "data summit" tagged only "summit"
    # still sneaks in if the name contains the topic):
    "developer", "devops", "platform", "engineering", "cloud",
    "kubernetes", "k8s", "containers",
}


async def ingest_developers_events(
    db: AsyncSession,
    *,
    filters: FeedFilters | None = None,
    actor_label: str = "feed_ingest",
) -> FeedIngestResult:
    """Pull the developers.events feed + persist matching rows."""
    filters = filters or FeedFilters()
    started = datetime.now(tz=UTC)
    log.info("feed.ingest.begin", source=DEVELOPERS_EVENTS_URL)

    settings = get_settings()  # noqa: F841 — held for future filter knobs

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Scout/0.1 (CFP discovery)"},
        ) as client:
            resp = await client.get(DEVELOPERS_EVENTS_URL)
            resp.raise_for_status()
            events: list[dict] = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.error("feed.fetch_failed", error=str(exc))
        return FeedIngestResult(
            source=DEVELOPERS_EVENTS_URL,
            total_in_feed=0,
            matched_filter=0,
            new_conferences=0,
            updated_conferences=0,
            skipped_duplicate=0,
            errors=1,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        )

    result = FeedIngestResult(
        source=DEVELOPERS_EVENTS_URL,
        total_in_feed=len(events),
        matched_filter=0,
        new_conferences=0,
        updated_conferences=0,
        skipped_duplicate=0,
        errors=0,
        started_at=started.isoformat(timespec="seconds"),
    )

    today = date.today()
    processed = 0
    for entry in events:
        if filters.limit is not None and processed >= filters.limit:
            break
        try:
            normalized = _normalize_entry(entry)
        except Exception as exc:
            log.warning(
                "feed.normalize_failed",
                name=str(entry.get("name", ""))[:80],
                error=str(exc),
            )
            result.errors += 1
            continue

        if normalized is None:
            continue  # malformed entry

        if filters.only_ai and not _looks_ai_related(entry, normalized):
            # Count it. Silent filtering is how 375 future conferences
            # went missing without anyone being able to tell.
            sd = normalized.get("start_date")
            if sd is None or sd >= today:
                result.dropped_by_keyword_filter += 1
            continue
        if (
            filters.future_only
            and normalized["start_date"]
            and normalized["start_date"] < today
        ):
            continue
        if (
            filters.only_status
            and entry.get("status")
            and str(entry["status"]).lower() not in filters.only_status
        ):
            continue

        result.matched_filter += 1
        processed += 1

        outcome = await _persist_event(
            db, normalized=normalized, actor_label=actor_label
        )
        if outcome == "new":
            result.new_conferences += 1
        elif outcome == "updated":
            result.updated_conferences += 1
        else:
            result.skipped_duplicate += 1

    await db.commit()
    result.finished_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    log.info(
        "feed.ingest.done",
        source=DEVELOPERS_EVENTS_URL,
        total_in_feed=result.total_in_feed,
        matched_filter=result.matched_filter,
        new=result.new_conferences,
        updated=result.updated_conferences,
        duplicates=result.skipped_duplicate,
        errors=result.errors,
    )
    return result


def _normalize_entry(entry: dict) -> dict | None:
    """Convert a developers.events entry to our Conference shape."""
    name = (entry.get("name") or "").strip()
    if not name or len(name) < 3:
        return None

    # `date` is [start_ms, end_ms] in epoch milliseconds; either can be 0/None.
    start_date, end_date = None, None
    raw_dates = entry.get("date") or []
    if isinstance(raw_dates, list) and len(raw_dates) >= 1 and raw_dates[0]:
        start_date = _epoch_ms_to_date(raw_dates[0])
    if isinstance(raw_dates, list) and len(raw_dates) >= 2 and raw_dates[1]:
        end_date = _epoch_ms_to_date(raw_dates[1])

    cfp = entry.get("cfp") or {}
    cfp_url = cfp.get("link") if isinstance(cfp, dict) else None
    cfp_close_at = None
    if isinstance(cfp, dict) and cfp.get("untilDate"):
        cfp_close_at = _epoch_ms_to_date(cfp["untilDate"])

    location_text = entry.get("location") or ""
    is_virtual = "online" in location_text.lower() or "virtual" in location_text.lower()
    country_raw = (entry.get("country") or "").strip()
    location_country = _country_to_iso2(country_raw)

    return {
        "name": name[:200],
        "start_date": start_date,
        "end_date": end_date,
        "location_city": (entry.get("city") or None) and entry["city"][:120],
        "location_country": location_country,
        "is_virtual": is_virtual,
        "website": (entry.get("hyperlink") or None) and entry["hyperlink"][:2000],
        "cfp_url": cfp_url and cfp_url[:2000],
        "cfp_close_at": cfp_close_at,
        # developers.events emits tags as either strings or
        # {key, value} dicts. Normalize to plain strings so they
        # don't render as Python reprs in the UI.
        "topics": _normalize_tags(entry.get("tags") or [])[:30],
        "raw_status": entry.get("status"),
    }


def _normalize_tags(raw_tags: list) -> list[str]:
    out: list[str] = []
    for t in raw_tags:
        if isinstance(t, str):
            v = t.strip()
        elif isinstance(t, dict):
            v = str(t.get("value") or t.get("key") or "").strip()
        else:
            v = str(t).strip()
        if v:
            out.append(v)
    return out


def _epoch_ms_to_date(value: Any) -> date | None:
    try:
        n = int(value)
        if n <= 0:
            return None
        return datetime.fromtimestamp(n / 1000, tz=UTC).date()
    except (TypeError, ValueError):
        return None


_COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "usa": "US", "united states": "US", "united states of america": "US",
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "france": "FR", "germany": "DE", "spain": "ES", "italy": "IT",
    "netherlands": "NL", "belgium": "BE", "switzerland": "CH",
    "austria": "AT", "portugal": "PT", "ireland": "IE", "denmark": "DK",
    "sweden": "SE", "norway": "NO", "finland": "FI", "poland": "PL",
    "czechia": "CZ", "czech republic": "CZ", "greece": "GR",
    "japan": "JP", "china": "CN", "south korea": "KR", "korea": "KR",
    "india": "IN", "singapore": "SG", "australia": "AU", "new zealand": "NZ",
    "canada": "CA", "mexico": "MX", "brazil": "BR", "argentina": "AR",
    "indonesia": "ID", "vietnam": "VN", "thailand": "TH", "malaysia": "MY",
    "uae": "AE", "united arab emirates": "AE", "israel": "IL",
    "honduras": "HN", "ukraine": "UA", "bangladesh": "BD", "nepal": "NP",
    "pakistan": "PK", "philippines": "PH",
}


def _country_to_iso2(raw: str) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if len(s) == 2:
        return s.upper()
    return _COUNTRY_NAME_TO_ISO2.get(s)


def _looks_ai_related(entry: dict, normalized: dict) -> bool:
    """Pass an event through the AI filter.

    Checks name + normalized topic strings + raw description if the feed
    provides one. The description matters: many AI events tag themselves
    generically (just "tech" or "developer") and carry the real topic
    signal only in their description text.

    Keywords come from `Settings.discovery_ai_keywords` so the operator
    can edit them at runtime from /settings/tunables. Falls back to the
    hardcoded `_AI_KEYWORDS` if the setting is empty (e.g. fresh DB).
    """
    name_lower = (normalized["name"] or "").lower()
    topic_lower = " ".join(normalized.get("topics", [])).lower()
    desc_lower = (
        str(entry.get("description") or entry.get("summary") or entry.get("about") or "")
        .lower()
    )
    blob = " ".join([name_lower, topic_lower, desc_lower])
    settings = get_settings()
    configured = [kw.lower() for kw in (settings.discovery_ai_keywords or []) if kw.strip()]
    keywords = configured if configured else list(_AI_KEYWORDS)
    return any(kw in blob for kw in keywords)


async def _persist_event(
    db: AsyncSession,
    *,
    normalized: dict,
    actor_label: str,
) -> str:
    """Returns 'new' / 'updated' / 'duplicate'. Caller commits."""
    slug = build_slug(normalized["name"], year_for(normalized.get("start_date")))
    existing = await find_duplicate(db, slug=slug)

    if existing is not None:
        # Field-merge: only fill in fields that are currently NULL on the
        # existing row. We don't want a feed re-ingest to overwrite a
        # human-curated bio with the feed's placeholder.
        changed = False
        for key in (
            "start_date",
            "end_date",
            "location_city",
            "location_country",
            "is_virtual",
            "website",
            "cfp_url",
            "cfp_close_at",
        ):
            if getattr(existing, key, None) in (None, "", False) and normalized.get(key):
                setattr(existing, key, normalized[key])
                changed = True
        if changed:
            await write_audit(
                db,
                action="conference.feed_merge",
                target_type="conference",
                target_id=existing.id,
                before=None,
                after=model_to_audit_dict(existing),
                actor_label=actor_label,
            )
            return "updated"
        return "duplicate"

    row = Conference(
        name=normalized["name"],
        slug=slug,
        start_date=normalized.get("start_date"),
        end_date=normalized.get("end_date"),
        location_city=normalized.get("location_city"),
        location_country=normalized.get("location_country"),
        is_virtual=normalized.get("is_virtual") or False,
        website=normalized.get("website"),
        cfp_url=normalized.get("cfp_url"),
        cfp_close_at=normalized.get("cfp_close_at"),
        cfp_deadlines=[],
        cfp_topics_of_interest=[],
        topics=normalized.get("topics") or [],
        # Feed data is more trustworthy than a single LLM extraction;
        # set the confidence high so the matcher's gate treats it well.
        confidence_score=0.9,
        status="discovered",
    )
    db.add(row)
    await db.flush()
    await write_audit(
        db,
        action="conference.feed_create",
        target_type="conference",
        target_id=row.id,
        before=None,
        after=model_to_audit_dict(row),
        actor_label=actor_label,
    )

    # Embed the conference text inline so the matcher's evidence
    # have something to compare against. Mirrors the extraction
    # pipeline; without this, every feed-ingested row scores 0 on
    # messaging and pillar (which we hit on the first ingest pass).
    # Best-effort: embed failure shouldn't block the row.
    try:
        blob = conference_embed_text(row)
        if blob:
            await embed_owner(
                db,
                owner_type="conference",
                owner_id=row.id,
                text=blob,
                purpose="embed:feed_conference",
            )
    except Exception as exc:
        log.warning("feed.embed_failed", conference_id=str(row.id), error=str(exc))

    # Enqueue the full enrich → re-embed → match flow as a background
    # task. The inline embed above gives the matcher *something* to
    # work with if the queued job is delayed; the queued job replaces
    # that with a properly enriched-text embedding + a real match row.
    # Local import keeps the scheduler dep out of the cold-import path.
    try:

        enqueue_task(
            "enrich_and_match",
            job_id=f"enrich-match-{row.id}",
            kwargs={"conference_id": str(row.id), "force": False},
        )
    except Exception as exc:
        log.warning(
            "feed.enqueue_match_failed",
            conference_id=str(row.id),
            error=str(exc),
        )

    return "new"


DISCOVERY_SOURCE_NAME = "Web discovery (autonomous)"


"""Singleton ``sources`` row that owns all discovery-fetched raw_pages."""


@dataclass(slots=True)
class DiscoveryHitOutcome:
    url: str
    title: str
    crawl_ok: bool
    parse_status: str | None = None
    conference_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class DiscoveryResult:
    """Returned from :func:`run_discovery`."""

    prompt: str
    provider: str
    requested: int
    search_hits: int
    crawled: int
    new_conferences: int
    updated_conferences: int
    parse_failures: int
    #: How many distinct search queries the sweep issued. 1 for a targeted
    #: run, keywords x templates x years for the scheduled one.
    queries: int = 1
    #: Candidates dropped at each stage, so a disappointing run can be
    #: diagnosed instead of guessed at. Recall is the objective; these are
    #: the numbers that say where recall is being lost.
    dropped_blocklist: int = 0
    #: Candidates whose hostname resolved to a private/loopback/link-local
    #: address. Non-zero is worth looking at — search results should not
    #: contain internal addresses, so it means something is pointing us
    #: inward on purpose.
    dropped_non_public: int = 0
    #: Candidates whose host's robots.txt forbids us. Same policy the
    #: curated scraper uses, so one deployment does not behave like a
    #: good citizen on one path and not the other.
    dropped_robots: int = 0
    dropped_url_cap: int = 0
    outcomes: list[DiscoveryHitOutcome] = field(default_factory=list)
    search_error: str | None = None
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


async def run_discovery(
    db: AsyncSession,
    *,
    prompt: str,
    max_results: int | None = None,
) -> DiscoveryResult:
    """Single end-to-end discovery run."""
    settings = get_settings()
    if not getattr(settings, "discovery_enabled", True):
        log.info("discovery.skipped.disabled")
        return DiscoveryResult(
            prompt=prompt,
            provider="(disabled)",
            requested=0,
            search_hits=0,
            crawled=0,
            new_conferences=0,
            updated_conferences=0,
            parse_failures=0,
            started_at=_now_iso(),
            finished_at=_now_iso(),
        )

    # Two modes. An explicit prompt is a targeted one-off — someone asked
    # for a specific thing and should get exactly that. No prompt means the
    # scheduled sweep, which expands the operator's keyword list into many
    # queries; that expansion is the whole reason a run finds hundreds of
    # conferences rather than twenty.
    k = max_results or int(getattr(settings, "discovery_max_results_per_query", 25))
    provider: SearchProvider = getattr(settings, "discovery_search_provider", "ddg")
    brave_key = _secret(settings, "discovery_brave_api_key")
    tavily_key = _secret(settings, "discovery_tavily_api_key")

    targeted = bool(prompt and prompt.strip())
    if targeted:
        queries = [prompt.strip()]
    else:
        this_year = datetime.now(tz=UTC).year
        queries = build_queries(
            keywords=list(getattr(settings, "discovery_keywords", []) or []),
            templates=list(getattr(settings, "discovery_query_templates", []) or []),
            years=[this_year, this_year + 1],
        )
        prompt = f"keyword sweep: {len(queries)} queries"

    result = DiscoveryResult(
        prompt=prompt,
        provider=str(provider),
        requested=k,
        queries=len(queries),
        search_hits=0,
        crawled=0,
        new_conferences=0,
        updated_conferences=0,
        parse_failures=0,
        started_at=_now_iso(),
        finished_at="",
    )

    # ---- 1. Search ----------------------------------------------------
    # web_search_many swallows per-query failures so one CAPTCHA does not
    # cost the whole sweep; a total failure still falls through to seeds.
    try:
        hits = await web_search_many(
            queries=queries,
            provider=provider,
            max_results_per_query=k,
            brave_api_key=brave_key,
            tavily_api_key=tavily_key,
        )
    except SearchError as exc:
        log.warning("discovery.search.failed", error=str(exc))
        result.search_error = str(exc)
        # don't return — seed URLs below still give us a signal floor.
        hits = []

    result.search_hits = len(hits)

    # ---- 1b. Merge in operator-configured seed URLs --------------------
    # These are aggregator / known-good conference hubs (aideadlin.es,
    # papercall.io, wikicfp, …). They give discovery a reliable signal
    # floor when the search backend returns nothing.
    seed_urls = list(getattr(settings, "discovery_seed_urls", []) or [])
    seed_hits: list[SearchHit] = [
        SearchHit(
            url=u,
            title="(seed)",
            snippet="Operator-configured discovery seed URL",
        )
        for u in seed_urls
    ]
    # Dedup by URL — search step may have already returned a seed.
    seen_urls: set[str] = {h.url for h in hits}
    for sh in seed_hits:
        if sh.url not in seen_urls:
            hits.append(sh)
            seen_urls.add(sh.url)

    # ---- 1c. URL blocklist --------------------------------------------
    # Drop known-junk patterns (wikipedia, openreview, social media, …)
    # before paying for a Crawl4AI fetch + LLM extraction.
    blocklist: list[str] = [
        b.lower()
        for b in (getattr(settings, "discovery_url_blocklist", []) or [])
        if b
    ]
    if blocklist:
        before_count = len(hits)
        hits = [
            h
            for h in hits
            if not any(b in h.url.lower() for b in blocklist)
        ]
        dropped = before_count - len(hits)
        result.dropped_blocklist = dropped
        if dropped:
            log.info("discovery.url_blocklist.dropped", count=dropped)

    # ---- 1c-2. SSRF screen ---------------------------------------------
    # These URLs come from search-engine results and from links mined off
    # aggregator pages — both influenceable by someone who is not us. They
    # are then handed to Crawl4AI, which drives a headless browser with its
    # own network stack, so the SSRF-guarded httpx transport in
    # services/discovery.py never sees them. Without this screen,
    # discovery is a request-forgery primitive aimed wherever a page says.
    #
    # This is a pre-flight DNS check, not the transport guard: it cannot
    # see a redirect to a private address, and a hostname that changes its
    # answer between here and the fetch defeats it. Crawl4AI owns the
    # fetch, so this is the strongest layer available without replacing it.
    before_ssrf = len(hits)
    hits = [h for h in hits if is_public_url(h.url)]
    result.dropped_non_public = before_ssrf - len(hits)
    if result.dropped_non_public:
        log.warning(
            "discovery.ssrf_screened",
            dropped=result.dropped_non_public,
            hint="a candidate URL resolved to a private/loopback/link-local address",
        )

    # ---- 1c-3. robots.txt ----------------------------------------------
    # The curated scraper has always honoured robots; discovery did not,
    # which meant the same deployment was a good citizen or not depending
    # on which code path found a page. Measured against the shipped seed
    # list this costs nothing — every reachable seed host allows us — so
    # there is no recall argument for skipping it, only a reputational one
    # for keeping it.
    hits = await _drop_robots_disallowed(hits, result)

    # ---- 1d. Run-level candidate cap -----------------------------------
    # A backstop, not a target. A hundred-keyword list can produce more
    # URLs than one run should crawl; this bounds the worst case without
    # quietly deciding what "enough conferences" is. Anything trimmed is
    # counted and logged, because a silent truncation reads as "we found
    # everything" when it is really "we stopped looking".
    url_cap = int(getattr(settings, "discovery_max_urls_per_run", 2000))
    if len(hits) > url_cap:
        result.dropped_url_cap = len(hits) - url_cap
        log.warning(
            "discovery.url_cap.truncated",
            cap=url_cap,
            dropped=result.dropped_url_cap,
            hint="raise discovery_max_urls_per_run if runs keep hitting this",
        )
        hits = hits[:url_cap]

    if not hits:
        log.info("discovery.no_candidate_urls")
        result.finished_at = _now_iso()
        return result

    # ---- 2. Crawl --------------------------------------------------------
    crawled = await crawl_many([h.url for h in hits])
    by_url: dict[str, SearchHit] = {h.url: h for h in hits}

    # ---- 2b. Follow conference-looking links from seed pages -----------
    # Aggregators (aideadlin.es / papercall.io / wikicfp) are *lists*
    # of conferences — the page itself is not_a_conference, but each
    # link points at one. Extract those, dedup against URLs we already
    # have, blocklist-filter, and crawl them depth=1. Caps how many
    # links any one page can contribute so a giant aggregator can't
    # dominate a single discovery run.
    seed_url_set = {u for u in seed_urls}
    discovered_links: list[str] = []
    already_seen_links: set[str] = {c.url for c in crawled}
    for c in crawled:
        if c.url not in seed_url_set:
            continue
        for link in extract_conference_links(
            c.markdown,
            source_url=c.url,
            blocklist_substrings=blocklist,
            max_links=int(
                getattr(settings, "discovery_max_links_per_seed", 30)
            ),
        ):
            if link in already_seen_links:
                continue
            already_seen_links.add(link)
            # Screen here too, and this is the path that needs it most:
            # these URLs are lifted verbatim out of third-party page
            # content, so anyone who can get a link onto an aggregator
            # chooses what we fetch. The search-result screen above does
            # not cover them — they never went through that list.
            if not is_public_url(link):
                result.dropped_non_public += 1
                log.warning(
                    "discovery.ssrf_screened_link",
                    link=link[:200],
                    from_seed=c.url[:200],
                )
                continue
            discovered_links.append(link)

    if discovered_links:
        log.info(
            "discovery.followed_links",
            count=len(discovered_links),
            from_seed_count=len(seed_url_set),
        )
        followup_crawled = await crawl_many(discovered_links)
        crawled.extend(followup_crawled)
        for link, hit in zip(
            discovered_links,
            [
                SearchHit(url=u, title="(followed)", snippet="From seed-URL page")
                for u in discovered_links
            ],
            strict=False,
        ):
            by_url.setdefault(link, hit)

    result.crawled = len(crawled)

    # ---- 3. Persist + extract -------------------------------------------
    src_id = await _get_or_create_discovery_source(db)

    for c in crawled:
        outcome = DiscoveryHitOutcome(
            url=c.url,
            title=c.title or (by_url.get(c.url).title if by_url.get(c.url) else "") or "",
            crawl_ok=True,
        )
        try:
            raw_page_id = await _persist_raw_page(
                db,
                source_id=src_id,
                crawled=c,
                snippet=by_url.get(c.url).snippet if by_url.get(c.url) else "",
            )
            if raw_page_id is None:
                outcome.error = "duplicate body (already fetched)"
                outcome.parse_status = "duplicate"
                result.outcomes.append(outcome)
                continue

            parse = await parse_raw_page(db, raw_page_id)
            await db.commit()
            outcome.parse_status = parse.parse_status
            outcome.conference_id = parse.conference_id
            if parse.ok:
                if parse.duplicate_of:
                    result.updated_conferences += 1
                else:
                    result.new_conferences += 1
            else:
                result.parse_failures += 1
        except Exception as exc:
            log.warning(
                "discovery.persist.failed",
                url=c.url,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            # An exception after a flush leaves the session in a poisoned
            # state; without this rollback every remaining page in the run
            # dies on PendingRollbackError — one flaky LLM call during the
            # 06:00 sweep turned into an hour of cascading "failures".
            await db.rollback()
            outcome.crawl_ok = False
            outcome.error = str(exc)[:200]
            result.parse_failures += 1
        result.outcomes.append(outcome)

    result.finished_at = _now_iso()
    log.info(
        "discovery.run.done",
        prompt_chars=len(prompt),
        provider=provider,
        search_hits=result.search_hits,
        crawled=result.crawled,
        new_conferences=result.new_conferences,
        parse_failures=result.parse_failures,
    )
    return result


async def _get_or_create_discovery_source(db: AsyncSession) -> UUID:
    """Singleton synthetic source that owns all discovery raw_pages."""
    row = (
        await db.execute(select(Source).where(Source.name == DISCOVERY_SOURCE_NAME))
    ).scalar_one_or_none()
    if row is not None:
        return row.id
    src = Source(
        name=DISCOVERY_SOURCE_NAME,
        url="internal://web-discovery",
        kind="page",  # closest existing kind; discovery has its own fetch path
        enabled=True,
        robots_allowed=True,
        politeness_delay_seconds=1,
    )
    db.add(src)
    await db.flush()
    log.info("discovery.source.created", source_id=str(src.id))
    return src.id


async def _persist_raw_page(
    db: AsyncSession,
    *,
    source_id: UUID,
    crawled,
    snippet: str,
) -> UUID | None:
    """Write the crawled body to disk + create a RawPage row. Returns the
    new row's id, or None if a row with the same content hash already
    exists (dedup)."""
    # Combine title + markdown + snippet into the body — the extraction
    # LLM only sees text, so we don't need the raw HTML; markdown is
    # cleaner input. snippet helps when the page is mostly nav + JS.
    body_parts: list[str] = []
    if crawled.title:
        body_parts.append(f"# {crawled.title}\n")
    body_parts.append(crawled.markdown or "")
    if snippet:
        body_parts.append(f"\n\n<!-- search-snippet -->\n{snippet}")
    body = "\n".join(body_parts).encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()

    existing = (await db.execute(select(RawPage).where(RawPage.hash == sha))).scalar_one_or_none()
    if existing is not None:
        return None

    path = save_raw_body(source_id, body, sha)
    row = RawPage(
        source_id=source_id,
        url=crawled.final_url or crawled.url,
        fetched_at=datetime.now(tz=UTC),
        http_status=crawled.status_code or 200,
        content_type="text/markdown",
        raw_body_path=str(path),
        hash=sha,
    )
    db.add(row)
    await db.flush()
    return row.id


async def _drop_robots_disallowed(
    hits: list[SearchHit], result: DiscoveryResult
) -> list[SearchHit]:
    """Remove candidates whose host's robots.txt forbids us.

    Uses the same RobotsCache the curated scraper uses, so one policy
    governs both fetch paths and a host is asked at most once a day.

    Failure is NOT treated as disallowed. If robots.txt cannot be fetched
    — the host is down, DNS is broken, the request times out — the URL
    stays in. A crawl policy that silently drops conferences whenever a
    network call fails would be a recall bug wearing a politeness costume,
    and RobotsCache already reads an unreachable or absent robots.txt as
    "everything allowed".
    """
    if not hits:
        return hits

    settings = get_settings()
    cache = RobotsCache()
    kept: list[SearchHit] = []
    async with make_async_client() as client:
        for h in hits:
            try:
                allowed = await cache.is_allowed(
                    h.url, settings.scraper_user_agent, client
                )
            except Exception as exc:
                log.debug(
                    "discovery.robots_check_failed",
                    url=h.url[:200],
                    error=str(exc)[:120],
                )
                allowed = True
            if allowed:
                kept.append(h)
            else:
                result.dropped_robots += 1

    if result.dropped_robots:
        log.info("discovery.robots_disallowed", dropped=result.dropped_robots)
    return kept


def _secret(settings, attr: str) -> str | None:
    value = getattr(settings, attr, None)
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return str(value) if value else None


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


# ==========================================================================
# source_service.py
# ==========================================================================


async def list_sources(
    db: AsyncSession,
    *,
    page: int,
    per_page: int,
    enabled: bool | None,
    kind: str | None,
) -> Page[SourceRead]:
    stmt = select(Source)
    if enabled is not None:
        stmt = stmt.where(Source.enabled.is_(enabled))
    if kind:
        stmt = stmt.where(Source.kind == kind)
    stmt = stmt.order_by(Source.created_at.desc())
    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[SourceRead](
        items=[SourceRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_source(db: AsyncSession, source_id: UUID) -> Source:
    row = await db.get(Source, source_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No source {source_id}",
        )
    return row


async def create_source(db: AsyncSession, payload: SourceCreate) -> Source:
    row = Source(
        name=payload.name,
        url=str(payload.url),
        kind=payload.kind.value,
        crawl_cadence=payload.crawl_cadence,
        politeness_delay_seconds=payload.politeness_delay_seconds,
        enabled=payload.enabled,
        notes=payload.notes,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source conflicts with an existing row (likely duplicate URL).",
        ) from exc
    await write_audit(
        db,
        action="source.create",
        target_type="source",
        target_id=row.id,
        before=None,
        after=model_to_audit_dict(row),
        actor_label="api.create_source",
    )
    log.info("source.created", source_id=str(row.id), kind=row.kind, url=row.url)
    return row


async def update_source(db: AsyncSession, source_id: UUID, payload: SourceUpdate) -> Source:
    row = await get_source(db, source_id)
    before = model_to_audit_dict(row)

    updated_any = False
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        if field_name == "url" and value is not None:
            value = str(value)
        setattr(row, field_name, value)
        updated_any = True

    if not updated_any:
        return row

    await db.flush()
    # TimestampedMixin's updated_at has onupdate=func.now(); flush expires
    # it so the new value can be loaded. Refresh explicitly here so the
    # subsequent model_to_audit_dict() access stays synchronous.
    await db.refresh(row)
    await write_audit(
        db,
        action="source.update",
        target_type="source",
        target_id=row.id,
        before=before,
        after=model_to_audit_dict(row),
        actor_label="api.update_source",
    )
    log.info("source.updated", source_id=str(row.id))
    return row


async def disable_source(db: AsyncSession, source_id: UUID) -> Source:
    """Soft delete = ``enabled = false``. Crawls + cron skip disabled rows."""
    row = await get_source(db, source_id)
    if not row.enabled:
        return row
    before = model_to_audit_dict(row)
    row.enabled = False
    await db.flush()
    # See update_source: refresh after flush so updated_at is re-loaded
    # synchronously rather than via SQLAlchemy's expired-attribute lazy load.
    await db.refresh(row)
    await write_audit(
        db,
        action="source.disable",
        target_type="source",
        target_id=row.id,
        before=before,
        after=model_to_audit_dict(row),
        actor_label="api.disable_source",
    )
    log.info("source.disabled", source_id=str(row.id))
    return row
