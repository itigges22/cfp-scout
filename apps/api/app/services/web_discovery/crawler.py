"""Crawl4AI wrapper — URL → clean markdown + page metadata.

Used by the discovery orchestrator after the search step has produced a
list of candidate URLs. We use Crawl4AI in its HTTP-only mode (no
Playwright) so the api container stays lean; JS-render mode is a future
enhancement when we hit a JS-heavy site that produces empty text.

SSRF guard, robots.txt, and politeness delays still apply — we don't
bypass the existing scraper/client layer's safety contract. Instead we
let Crawl4AI handle the actual fetch (it has its own robots-respect +
politeness primitives) and then feed the resulting markdown back into
Scout's normal raw_pages → extraction → matcher path.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

log = structlog.get_logger("scout.discovery.crawler")


@dataclass(slots=True, frozen=True)
class CrawlResult:
    url: str
    final_url: str  # post-redirect
    status_code: int
    markdown: str
    raw_html_bytes: int
    title: str | None


class CrawlError(RuntimeError):
    """Surfaced when Crawl4AI fails for a given URL."""


_PER_URL_TIMEOUT_SECONDS = 30.0


async def crawl_one(url: str) -> CrawlResult:
    """Fetch ``url`` via Crawl4AI, return clean markdown + metadata.

    Caller is responsible for batching multiple URLs (Crawl4AI's session
    is heavy to construct; reuse via :func:`crawl_many` when possible).
    Raises :class:`CrawlError` on any failure — the orchestrator catches
    + skips the URL.
    """
    results = await crawl_many([url])
    if not results:
        raise CrawlError(f"crawl4ai returned no result for {url}")
    return results[0]


async def crawl_many(urls: list[str]) -> list[CrawlResult]:
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

    out: list[CrawlResult] = []
    log.info("discovery.crawl.begin", url_count=len(urls))

    async with AsyncWebCrawler(
        crawler_strategy=AsyncHTTPCrawlerStrategy(),
        verbose=False,
    ) as crawler:
        for url in urls:
            try:
                async with asyncio.timeout(_PER_URL_TIMEOUT_SECONDS):
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
                CrawlResult(
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
