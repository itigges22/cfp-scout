"""Single-URL fetch + dedupe + persist (plan 14).

The "leaf" of the scraper pipeline. Given a candidate URL plus the politeness
and storage helpers, this does:

  1. robots.txt check (skip with ``parse_status='robots_disallowed'``)
  2. per-host rate-limit acquire
  3. conditional GET via ETag / Last-Modified from any prior fetch
  4. content sha256
  5. dedupe by hash — if a row exists under the same source with the same
     hash, bump ``fetched_at`` and skip the write
  6. persist body to volume + insert ``raw_pages`` row
  7. return a small typed result so the caller can update stats

This function never raises on a per-URL failure — it logs + returns a
``FetchOutcome.error()`` record so the surrounding crawl can keep going.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import RawPage
from app.services.scraper.politeness import RateLimiter, RobotsCache
from app.services.scraper.storage import compute_sha256, save_raw_body

log = structlog.get_logger("scout.scraper.fetch")

# Plan threshold: under this many chars of HTML and the source is almost
# certainly JS-rendered. Flag for follow-up rather than dropping silently.
JS_RENDER_THRESHOLD = 500

# Hard cap on per-page body size. 5 MB is generous for conference pages and
# prevents a runaway source from filling the volume.
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
    def error_outcome(cls, url: str, error: str) -> "FetchOutcome":
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
    except Exception as exc:  # noqa: BLE001 — robots failures are non-fatal
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
        existing.fetched_at = datetime.now(tz=timezone.utc)
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
    parse_status = "needs_js_render" if text_len < JS_RENDER_THRESHOLD else None

    row = RawPage(
        source_id=source_id,
        url=url,
        fetched_at=datetime.now(tz=timezone.utc),
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


async def _find_prior_fetch(
    db: AsyncSession, source_id: UUID, url: str
) -> RawPage | None:
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
    except Exception:  # noqa: BLE001 — fallback to raw if parser blows up
        return len(body)
