"""End-to-end extraction pipeline (plan 15).

Given a ``raw_pages`` row id, run the full path:

  1. Load raw_pages row + read the body off disk
  2. Strip boilerplate (trafilatura)
  3. Call the LLM to extract a structured ``ExtractedConference``
  4. Validate (Pydantic already enforced shape; run business rules)
  5. Score (LLM × structural × rule-penalties)
  6. Route (discovered / needs_review / quarantined)
  7. Slug-dedupe against existing ``conferences``; create or merge
  8. Normalize topics against the controlled vocab; insert pending ones
  9. Add ``conference_sources`` junction row for traceability
  10. Update ``raw_pages.parse_status``
  11. Return a typed ``ParseResult`` for the caller (admin route or task
      runner) to log / surface

The function never raises on extraction failure — it routes the row to
``parse_status='extraction_failed'`` and returns ``ParseResult(ok=False)``.
That way the scrape can keep going for sibling pages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    Conference,
    ConferenceSource,
    RawPage,
)
from app.services.extraction.cleaning import clean_html_to_text
from app.services.extraction.dedup import build_slug, find_duplicate, year_for
from app.services.extraction.llm_extract import extract
from app.services.extraction.prompts import PROMPT_VERSION
from app.services.extraction.schema import ExtractedConference
from app.services.extraction.topics import normalize_topics
from app.services.extraction.validation import (
    ValidationOutcome,
    validate_and_score,
)

log = structlog.get_logger("scout.extraction.pipeline")


@dataclass(slots=True)
class ParseResult:
    """Returned by :func:`parse_raw_page`.

    Serializable via ``asdict`` for the task runner's ingest_jobs.stats payload.
    """

    raw_page_id: str
    ok: bool
    parse_status: str
    conference_id: str | None = None
    conference_slug: str | None = None
    duplicate_of: str | None = None  # set when we merged into an existing row
    confidence: float | None = None
    structural_confidence: float | None = None
    rule_penalty: float | None = None
    status: str | None = None
    quarantine_reasons: list[str] = field(default_factory=list)
    pending_topics: list[str] = field(default_factory=list)
    error: str | None = None
    prompt_version: str = PROMPT_VERSION

    def to_stats(self) -> dict:
        return asdict(self)


async def parse_raw_page(db: AsyncSession, raw_page_id: UUID) -> ParseResult:
    """Run the full extraction pipeline for one raw_page."""
    row = await db.get(RawPage, raw_page_id)
    if row is None:
        return ParseResult(
            raw_page_id=str(raw_page_id),
            ok=False,
            parse_status="missing",
            error=f"no raw_page {raw_page_id}",
        )

    bound = log.bind(raw_page_id=str(row.id), url=row.url)

    # ---- 1. Read body off disk ----------------------------------------
    body_path = Path(row.raw_body_path)
    if not body_path.exists():
        row.parse_status = "missing_body"
        bound.warning("extraction.body_missing", path=str(body_path))
        return ParseResult(
            raw_page_id=str(row.id),
            ok=False,
            parse_status="missing_body",
            error=f"body file not found at {body_path}",
        )

    body_bytes = body_path.read_bytes()

    # ---- 2. Clean HTML -------------------------------------------------
    cleaned = clean_html_to_text(body_bytes, content_type=row.content_type)
    if not cleaned or len(cleaned) < 100:
        row.parse_status = "insufficient_text"
        bound.info("extraction.insufficient_text", cleaned_len=len(cleaned))
        return ParseResult(
            raw_page_id=str(row.id),
            ok=False,
            parse_status="insufficient_text",
            error=f"cleaned text too short ({len(cleaned)} chars)",
        )

    # ---- 3. LLM extract -----------------------------------------------
    extracted, err = await extract(db=db, page_text=cleaned, source_url=row.url)
    if extracted is None:
        row.parse_status = "extraction_failed"
        bound.info("extraction.failed", error=err)
        return ParseResult(
            raw_page_id=str(row.id),
            ok=False,
            parse_status="extraction_failed",
            error=err,
        )

    # ---- 4-6. Validate + route ----------------------------------------
    outcome = validate_and_score(extracted)
    bound.info(
        "extraction.scored",
        name=extracted.name,
        llm_confidence=extracted.confidence,
        structural_confidence=outcome.structural_confidence,
        rule_penalty=outcome.rule_penalty,
        final=outcome.final_confidence,
        status=outcome.status,
    )

    # Edge case: model returned ``{"name": "Unknown"}`` to signal "no
    # conference here". Quarantine deterministically.
    if extracted.name == "Unknown":
        outcome.final_confidence = 0.0
        outcome.status = "quarantined"

    # ---- 7. Slug dedupe + persist -------------------------------------
    slug = build_slug(extracted.name, year_for(extracted.start_date))
    existing = await find_duplicate(db, slug=slug)

    if existing is not None:
        conference = existing
        duplicate_of = str(existing.id)
        # For pass 1 we don't field-merge — we just attach this raw_page to
        # the existing conference so the matcher (plan 17) sees the new
        # evidence. Field-merge + content_versions land in pass 2.
        bound.info("extraction.duplicate_slug", slug=slug, existing=str(existing.id))
    else:
        conference = Conference(
            name=extracted.name,
            slug=slug,
            start_date=extracted.start_date,
            end_date=extracted.end_date,
            location_city=extracted.location_city,
            location_country=(
                extracted.location_country.upper() if extracted.location_country else None
            ),
            is_virtual=extracted.is_virtual,
            venue=extracted.venue,
            website=extracted.website,
            cfp_open_at=extracted.cfp_open_at,
            cfp_close_at=extracted.cfp_close_at,
            cfp_deadlines=[d.model_dump(mode="json") for d in extracted.cfp_deadlines],
            cfp_topics_of_interest=list(extracted.cfp_topics_of_interest),
            acceptance_rate_percent=extracted.acceptance_rate_percent,
            estimated_cost_usd=extracted.estimated_cost_usd,
            topics=[],  # filled below from topic normalization
            confidence_score=outcome.final_confidence,
            status=outcome.status,
        )
        db.add(conference)
        await db.flush()  # populates conference.id
        duplicate_of = None
        bound.info(
            "extraction.persisted",
            conference_id=str(conference.id),
            slug=slug,
            status=outcome.status,
        )

    # ---- 8. Topic normalization --------------------------------------
    canonical_topics, pending_new = await normalize_topics(db, extracted.topics)
    if canonical_topics and not duplicate_of:
        # Only set topics on newly-created rows; dedup-merge leaves
        # existing topics alone (pass 2 will handle merge logic).
        conference.topics = canonical_topics

    # ---- 9. conference_sources junction ------------------------------
    junction_exists = await db.execute(
        select(ConferenceSource).where(
            ConferenceSource.conference_id == conference.id,
            ConferenceSource.raw_page_id == row.id,
        )
    )
    if junction_exists.scalar_one_or_none() is None:
        db.add(
            ConferenceSource(
                conference_id=conference.id,
                raw_page_id=row.id,
            )
        )

    # ---- 10. raw_pages.parse_status ----------------------------------
    row.parse_status = "extracted"

    await db.flush()
    return ParseResult(
        raw_page_id=str(row.id),
        ok=True,
        parse_status="extracted",
        conference_id=str(conference.id),
        conference_slug=conference.slug,
        duplicate_of=duplicate_of,
        confidence=round(outcome.final_confidence, 3),
        structural_confidence=outcome.structural_confidence,
        rule_penalty=round(outcome.rule_penalty, 3),
        status=outcome.status,
        quarantine_reasons=outcome.quarantine_reasons,
        pending_topics=pending_new,
    )
