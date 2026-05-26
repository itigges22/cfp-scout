"""Background task: enrich + (re-)embed + score one conference.

Runs the full "process a newly-arrived conference" sequence in one
APScheduler job:

  1. LLM-enrich the conference (name + topics + location → 2-3 sentence
     factual description with real technical vocabulary). Skipped when
     ``enriched_description`` is already populated and ``force`` is
     False — keeps re-runs cheap.
  2. Re-embed the conference text using the enriched description, so
     the matcher's stage A + B compare against the rich text instead
     of the 14-word bare blob.
  3. Run the matcher (``run_fit_match_task``) to produce a fresh
     :class:`Match` row.

Replaces the prior pattern where ingest paths called
:func:`run_fit_match_task` directly — that worked, but the matcher
saw whatever embed text was already on disk, which for feed-ingested
or newly-extracted rows is the bare name+topics blob (median 14
words) and produces near-zero messaging scores.

Idempotent. Safe to enqueue multiple times for the same conference;
only the most-recently-finished run's match row sticks.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, select, update

from app.db.models.entities import Conference
from app.db.models.vectors import DocumentChunk
from app.db.session import get_session_factory
from app.services.embeddings import embed_owner
from app.services.enrichment import enrich_conference
from app.services.extraction.pipeline import _conference_embed_text
from app.tasks.run_fit_match import _do_run_fit_match

log = structlog.get_logger("scout.tasks.enrich_and_match")


async def enrich_and_match_task(
    *,
    conference_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Enrich + re-embed + match one conference. Returns a status dict.

    ``force`` re-runs enrichment even when ``enriched_description`` is
    already populated. Useful for refreshing rows after messaging
    documents change (so the LLM gets a chance to re-extract).
    """
    bound = log.bind(conference_id=conference_id)
    bound.info("enrich_and_match.start", force=force)

    conf_uuid = UUID(conference_id)
    session_factory = get_session_factory()

    # Step 1 + 2: enrichment + re-embed share one session so a single
    # transaction commits both the description and the chunk row.
    async with session_factory() as db:
        conf = (
            await db.execute(select(Conference).where(Conference.id == conf_uuid))
        ).scalar_one_or_none()
        if conf is None:
            bound.warning("enrich_and_match.not_found")
            return {"ok": False, "reason": "conference_not_found"}
        if conf.status == "quarantined":
            bound.info("enrich_and_match.skip_quarantined")
            return {"ok": False, "reason": "quarantined"}

        enriched = False
        if force or not conf.enriched_description:
            new_desc = await enrich_conference(
                db=db,
                name=conf.name,
                topics=list(conf.topics or []),
                country=conf.location_country,
                city=conf.location_city,
                is_virtual=bool(conf.is_virtual),
            )
            if new_desc:
                await db.execute(
                    update(Conference)
                    .where(Conference.id == conf.id)
                    .values(enriched_description=new_desc)
                )
                conf.enriched_description = new_desc
                enriched = True
                bound.info("enrich_and_match.enriched", chars=len(new_desc))
            else:
                bound.warning("enrich_and_match.enrich_failed")
        else:
            bound.info("enrich_and_match.enrich_skipped_existing")

        # Re-embed — drop old chunks first so we don't accumulate
        # multiple embeddings per conference across re-runs.
        await db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.owner_type == "conference",
                DocumentChunk.owner_id == conf.id,
            )
        )
        text = _conference_embed_text(conf)
        embedded = False
        if text.strip():
            try:
                await embed_owner(
                    db,
                    owner_type="conference",
                    owner_id=conf.id,
                    text=text,
                    purpose="embed:enrich_and_match",
                )
                embedded = True
            except Exception as exc:  # noqa: BLE001 — non-fatal
                bound.warning("enrich_and_match.embed_failed", error=str(exc))
        await db.commit()

    # Step 3: matcher. ``_do_run_fit_match`` owns its own session so we
    # commit the enrichment + embed first (above), then run the
    # matcher against the freshly-persisted chunks. Returns a dict
    # (``MatchResult.to_stats()``) with messaging/pillar/sme/overall.
    try:
        match_stats = await _do_run_fit_match(conference_id=conference_id)
        bound.info(
            "enrich_and_match.matched",
            overall=match_stats.get("overall_score"),
        )
        return {
            "ok": True,
            "enriched": enriched,
            "embedded": embedded,
            "overall_score": match_stats.get("overall_score"),
            "messaging_score": match_stats.get("messaging_score"),
            "pillar_score": match_stats.get("pillar_score"),
            "sme_score": match_stats.get("sme_score"),
        }
    except Exception as exc:  # noqa: BLE001 — non-fatal
        bound.warning("enrich_and_match.matcher_failed", error=str(exc))
        return {
            "ok": False,
            "enriched": enriched,
            "embedded": embedded,
            "reason": f"matcher_failed: {exc!s}",
        }


__all__ = ["enrich_and_match_task"]
