"""Web-search adapters for discovery.

Three providers, picked at runtime via the ``discovery_search_provider``
setting:

  * ``ddg``    — DuckDuckGo HTML search. No API key, free, default.
  * ``brave``  — Brave Search API. Free tier 1 query/s + 2000/month.
                 Requires ``discovery_brave_api_key``.
  * ``tavily`` — Tavily AI-friendly search. Free tier 1000/month.
                 Requires ``discovery_tavily_api_key``.

All three return :class:`SearchHit` objects so the orchestrator doesn't
care which backend ran. Each adapter is responsible for its own rate
limiting and graceful failure on quota exhaustion — they raise
:class:`SearchError` so the caller can surface a clean operational
message instead of a stack trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx
import structlog

log = structlog.get_logger("scout.discovery.search")

SearchProvider = Literal["ddg", "brave", "tavily"]


class SearchError(RuntimeError):
    """Any provider-level failure (quota, auth, network)."""


@dataclass(slots=True, frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    score: float | None = None  # provider-supplied relevance; None for DDG


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# DuckDuckGo HTML
# ---------------------------------------------------------------------------
async def _search_ddg(prompt: str, max_results: int) -> list[SearchHit]:
    """Wraps ``duckduckgo_search.DDGS`` in a threadpool — DDGS is sync
    and the library doesn't ship an async API yet.

    DDG is *aggressively* rate-limited: empty result pages and CAPTCHA
    fallbacks happen mid-stream. We retry with exponential backoff up
    to 3 times. If the prompt is >120 chars the search box also tends
    to return nothing, so we fall back to a truncated version on the
    second attempt.
    """
    import asyncio

    from anyio import to_thread

    def _run(query: str) -> list[SearchHit]:
        # Local import — duckduckgo_search has a noisy import path that
        # we don't want at module-level (slow startup).
        from duckduckgo_search import DDGS

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


# ---------------------------------------------------------------------------
# Brave Search API
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Tavily Search API
# ---------------------------------------------------------------------------
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
