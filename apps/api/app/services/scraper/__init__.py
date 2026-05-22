"""Scraper package (plan 14).

Public surface:
  * :func:`crawl_source` — full crawl pipeline for a single source row
  * :func:`make_async_client` — SSRF-guarded httpx.AsyncClient factory

Internals (not re-exported, but stable enough to import):
  * :mod:`.client`      — SSRF-guarded transport
  * :mod:`.discovery`   — kind-specific URL discovery (rss, page, ...)
  * :mod:`.fetch`       — single-URL fetch + dedupe + persist
  * :mod:`.politeness`  — robots.txt cache + per-host rate limit
  * :mod:`.storage`     — disk layout for the raw_pages volume
"""

from app.services.scraper.client import make_async_client
from app.services.scraper.pipeline import CrawlResult, crawl_source

__all__ = ["CrawlResult", "crawl_source", "make_async_client"]
