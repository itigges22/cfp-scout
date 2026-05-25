"""Structured-feed ingestion — skip the LLM extraction step.

For known-good upstream JSON feeds (developers.events, conference-hall,
etc.) we already have clean structured data: name, dates, location,
homepage, CFP url + deadline. The LLM-extraction-per-page path that
:mod:`web_discovery.orchestrator` runs is wasted on these — both
expensive and lossy.

This module ingests the feed directly: HTTP GET → JSON parse →
Conference row per event. The structural data already meets the
extraction schema's bar; we set ``confidence_score=0.9`` since a
maintained feed is trustworthier than a one-shot LLM extraction.

After ingest, the rows pass through the same matcher + embed paths as
scraper-discovered conferences, so they show up in /conferences and
get scored against messaging + pillars + SMEs normally.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference
from app.services._common import model_to_audit_dict, write_audit
from app.services.embeddings import embed_owner
from app.services.extraction.dedup import build_slug, find_duplicate, year_for
from app.services.extraction.pipeline import _conference_embed_text
from app.services.graph import invalidate as invalidate_graph
from app.settings import get_settings

log = structlog.get_logger("scout.discovery.feeds")

DEVELOPERS_EVENTS_URL = "https://developers.events/all-events.json"


@dataclass(slots=True)
class FeedIngestResult:
    """Returned by :func:`ingest_developers_events`."""

    source: str
    total_in_feed: int
    matched_filter: int  # passed AI-tag + future-date filters
    new_conferences: int
    updated_conferences: int
    skipped_duplicate: int
    errors: int
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class FeedFilters:
    only_ai: bool = True
    future_only: bool = True
    limit: int | None = None
    # When set, only ingest events with status in this set (feed uses
    # 'open' / 'past' / 'cancelled').
    only_status: set[str] = field(
        default_factory=lambda: {"open"}
    )


# AI / ML / data-relevant tag and name keywords. Both the feed's
# `tags` array AND the event name get checked, since the maintainers'
# tagging is wildly inconsistent.
#
# Tuned aggressively wide on purpose — the user wants Scout to surface
# meetups, hackathons, panels, workshops, summits, and conferences. The
# matcher's scoring stage will rank low-fit events to the bottom, but
# we want them in the universe first. False positives are cheap; missed
# AI events are expensive.
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
            continue
        if filters.future_only and normalized["start_date"]:
            if normalized["start_date"] < today:
                continue
        if filters.only_status and entry.get("status"):
            if str(entry["status"]).lower() not in filters.only_status:
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
    invalidate_graph()
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


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
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


# Common country names → ISO-3166-1 alpha-2. Not exhaustive — the
# matcher's location stage falls back gracefully on missing codes.
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
    provides one. Many AI events tag themselves generically (just "tech"
    or "developer") and put the topic signal in the description — those
    used to be silently dropped.

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


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
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

    # Embed the conference text inline so the matcher's Stage A + B
    # have something to compare against. Mirrors the extraction
    # pipeline; without this, every feed-ingested row scores 0 on
    # messaging and pillar (which we hit on the first ingest pass).
    # Best-effort: embed failure shouldn't block the row.
    try:
        blob = _conference_embed_text(row)
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

    return "new"
