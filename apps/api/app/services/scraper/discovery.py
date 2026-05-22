"""URL discovery per source kind (plan 14, pass 1).

Given a ``Source`` row, yield the list of URLs the crawler should fetch.
Pass 1 supports two kinds; pass 2 adds the rest:

  * ``rss``  — RSS / Atom feed parsed via feedparser
  * ``page`` — static HTML page with conference links; we fetch the page,
               extract every ``<a href>`` whose URL is on the same host or
               points at a likely-conference subpath.

Pass 2 will add ``sitemap``, ``ics``, ``wikicfp``, ``api``.
"""

from __future__ import annotations

import urllib.parse

import feedparser
import httpx
import structlog
from selectolax.lexbor import LexborHTMLParser

log = structlog.get_logger("scout.scraper.discovery")

# Cap on URLs returned per discovery run. Plan calls for max 100 per source
# per crawl. Combined with the per-host rate limit this bounds a single
# scrape to ~5 minutes wallclock.
MAX_URLS_PER_DISCOVERY = 100


async def discover_urls(
    *,
    kind: str,
    url: str,
    client: httpx.AsyncClient,
) -> list[str]:
    """Dispatch on ``kind`` and return up to :data:`MAX_URLS_PER_DISCOVERY`
    candidate URLs.

    The fetch policy for the discovery request itself is the same as for
    target URLs — robots + rate-limit applied by the caller, never here.
    """
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
        if len(urls) >= MAX_URLS_PER_DISCOVERY:
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
        if len(out) >= MAX_URLS_PER_DISCOVERY:
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
