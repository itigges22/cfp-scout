"""Discovery orchestrator — wires search → crawl → existing extraction.

Single entry point: :func:`run_discovery`. Caller (admin endpoint OR
cron job) passes in a template prompt + max_results; the function
returns a :class:`DiscoveryResult` summarizing what landed.

Reuses ~80% of the existing pipeline once it's produced a ``RawPage``
row + body on disk:

  1. ``run_discovery`` runs search and Crawl4AI fetch
  2. For each successful crawl, write the markdown to disk + create a
     ``RawPage`` row owned by the synthetic "Web discovery" source
  3. Dispatch to ``app.services.extraction.pipeline.parse_raw_page`` —
     the same LLM extraction that the curated scraper uses
  4. The extraction pipeline already auto-enqueues the matcher
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import RawPage, Source
from app.services.extraction.pipeline import parse_raw_page
from app.services.scraper.storage import save_raw_body
from app.services.web_discovery.crawler import crawl_many
from app.services.web_discovery.search import (
    SearchError,
    SearchHit,
    SearchProvider,
    web_search,
)
from app.settings import get_settings

log = structlog.get_logger("scout.discovery.orchestrator")

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

    if not prompt or not prompt.strip():
        prompt = getattr(
            settings,
            "discovery_template_prompt",
            "AI conferences with CFP open in the next 6 months on LLMs, RAG, "
            "MLOps, agentic AI, model serving, AI safety",
        )

    k = max_results or int(getattr(settings, "discovery_max_results_per_run", 20))
    provider: SearchProvider = getattr(settings, "discovery_search_provider", "ddg")
    brave_key = _secret(settings, "discovery_brave_api_key")
    tavily_key = _secret(settings, "discovery_tavily_api_key")

    result = DiscoveryResult(
        prompt=prompt,
        provider=str(provider),
        requested=k,
        search_hits=0,
        crawled=0,
        new_conferences=0,
        updated_conferences=0,
        parse_failures=0,
        started_at=_now_iso(),
        finished_at="",
    )

    # ---- 1. Search ----------------------------------------------------
    try:
        hits = await web_search(
            prompt=prompt,
            provider=provider,
            max_results=k,
            brave_api_key=brave_key,
            tavily_api_key=tavily_key,
        )
    except SearchError as exc:
        log.warning("discovery.search.failed", error=str(exc))
        result.search_error = str(exc)
        result.finished_at = _now_iso()
        return result

    result.search_hits = len(hits)
    if not hits:
        result.finished_at = _now_iso()
        return result

    # ---- 2. Crawl --------------------------------------------------------
    crawled = await crawl_many([h.url for h in hits])
    result.crawled = len(crawled)
    by_url: dict[str, SearchHit] = {h.url: h for h in hits}

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _secret(settings, attr: str) -> str | None:
    value = getattr(settings, attr, None)
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return str(value) if value else None


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
