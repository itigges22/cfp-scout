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
from app.db.models.junctions import ConferenceTopic
from app.services.embeddings import embed_owner
from app.services.extraction.cleaning import clean_html_to_text
from app.services.extraction.dedup import build_slug, find_duplicate, year_for
from app.services.extraction.llm_extract import extract
from app.services.extraction.prompts import PROMPT_VERSION
from app.services.extraction.topics import normalize_topics
from app.services.extraction.validation import (
    validate_and_score,
)
from app.services.graph import invalidate as invalidate_graph

log = structlog.get_logger("scout.extraction.pipeline")


def _conference_embed_text(c: Conference) -> str:
    """Compose the descriptive blob we embed for the matcher.

    Prefers the LLM-generated ``enriched_description`` when present —
    that text contains real technical vocabulary (vLLM, MLOps, RAG,
    etc.) that lets cosine similarity actually find alignment with
    messaging documents. Without enrichment, the bare name+topics blob
    is 14 words median and the matcher scores almost everything 0%.

    Falls back to the bare structural fields when enrichment hasn't
    run yet (NULL ``enriched_description`` on freshly-ingested rows
    before the enrichment pass).
    """
    parts: list[str] = [c.name]
    if c.enriched_description:
        parts.append(c.enriched_description)
    if c.topics:
        parts.append("Topics: " + ", ".join(c.topics))
    if c.cfp_topics_of_interest:
        parts.append("CFP topics: " + ", ".join(c.cfp_topics_of_interest))
    if c.location_city or c.location_country:
        loc = " / ".join(p for p in (c.location_city, c.location_country) if p)
        parts.append(f"Location: {loc}")
    if c.is_virtual:
        parts.append("Virtual event.")
    if c.venue:
        parts.append(f"Venue: {c.venue}")
    return "\n".join(parts)


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
    # conference here". Don't create a Conference row at all — flag
    # the raw_page as not_a_conference and bail out so the autonomous
    # discovery flow doesn't pollute the dashboard with a synthetic
    # 'unknown-unknown' row that every subsequent junk URL would then
    # get dedup-merged into.
    if extracted.name == "Unknown":
        row.parse_status = "not_a_conference"
        bound.info(
            "extraction.not_a_conference",
            llm_confidence=extracted.confidence,
        )
        return ParseResult(
            raw_page_id=str(row.id),
            ok=False,
            parse_status="not_a_conference",
            confidence=extracted.confidence,
            structural_confidence=outcome.structural_confidence,
            rule_penalty=outcome.rule_penalty,
        )

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
            cfp_url=extracted.cfp_url,
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
    canonical_topics, pending_new, matched_topic_rows = await normalize_topics(db, extracted.topics)
    if canonical_topics and not duplicate_of:
        # Only set topics on newly-created rows; dedup-merge leaves
        # existing topics alone (pass 2 will handle merge logic).
        conference.topics = canonical_topics

    # Conference -> Topic junction rows (plan 16 graph edges). Idempotent
    # via composite PK + ON CONFLICT-free insert protected by an existence
    # check (small N per conference; not worth a raw INSERT ON CONFLICT).
    if matched_topic_rows:
        existing_ct = await db.execute(
            select(ConferenceTopic.topic_id).where(ConferenceTopic.conference_id == conference.id)
        )
        already = {tid for (tid,) in existing_ct.all()}
        for topic in matched_topic_rows:
            if topic.id in already:
                continue
            db.add(
                ConferenceTopic(
                    conference_id=conference.id,
                    topic_id=topic.id,
                    weight=1.0,
                )
            )

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
    # Junction tables changed (ConferenceTopic + ConferenceSource) — drop
    # the in-memory graph cache so the next read picks up the new edges.
    invalidate_graph()

    # ---- 11. Conference embedding (powers plan 17 Stage A) -----------
    # Compose a small descriptive blob from the structured fields. We
    # deliberately exclude the raw cleaned text (already embedded as raw_page
    # chunks in a future plan) — this lightweight description is what the
    # matcher's messaging-similarity gate compares against. Failure is
    # non-fatal; admin can rerun via /admin/embeddings/embed-owner.
    try:
        blob = _conference_embed_text(conference)
        if blob:
            await embed_owner(
                db,
                owner_type="conference",
                owner_id=conference.id,
                text=blob,
                purpose="embed:conference",
            )
    except Exception as exc:
        bound.warning("extraction.conference_embed_failed", error=str(exc))

    # ---- 12. Enqueue plan-17 matcher (skip quarantined) --------------
    # Local import avoids a circular dep (scheduler -> tasks -> extraction
    # would chain back here in the tasks/parse_raw_page path).
    if outcome.status != "quarantined":
        from app.scheduler import enqueue_now
        from app.tasks.run_fit_match import run_fit_match_task

        enqueue_now(
            run_fit_match_task,
            job_id=f"match-{conference.id}",
            kwargs={"conference_id": str(conference.id)},
        )
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
