"""Everything that runs in the background, and the wrapper they share.

WHAT THIS DOES
    ``run_as_job`` opens a session, writes an ``ingest_jobs`` row, times
    the work, records status and stats, and never lets an exception escape
    into the scheduler. Every task below runs inside it:

        heartbeat          liveness marker
        scrape_source      poll one curated Source
        parse_raw_page     RawPage -> Conference
        run_discovery      the deep web sweep
        enrich_and_match   fill gaps, then score
        run_fit_match      score one conference
        build_cfp_digest   the recurring deadline summary

HOW IT CONNECTS
    Called by   app/scheduler.py register_jobs (the cron ones), the admin
                routes, and services that enqueue after they commit
    Reads/writes app.ingest_jobs, plus whatever each task touches
    Helpers     app/db/session.py, app/scheduler.py
    Tuning      settings.scheduler_mode, settings.scheduler_timezone

WORTH KNOWING
    Eight files, and ``_runner`` — the wrapper all of them are defined in
    terms of — had no consumer outside the package. Reading any one task
    meant opening the runner beside it to know what happens on failure.

    APScheduler runs one instance of a job id at a time and coalesces
    missed fires, so enqueuing the same id twice collapses into one run.
    Every task must be safe to re-run with the same arguments.

    Tasks NEVER write conference status — that is a human decision. See
    tests/unit/test_no_background_job_writes_status.py.
"""

from __future__ import annotations

import time
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy import text as sql_text

from app.db.models import Conference, IngestJob, Match, Source
from app.db.session import get_session_factory
from app.services.conferences import conference_embed_text, enrich_conference
from app.services.discovery import SourceDisabledError, SourceNotFoundError, run_discovery
from app.services.discovery import crawl_source as run_crawl_source
from app.services.embeddings import embed_owner
from app.services.extraction import parse_raw_page
from app.services.matcher import (
    ALGORITHM_VERSION,
    ConferenceNotFoundError,
    ConferenceQuarantinedError,
    run_fit_match,
)
from app.services.reports import build_cfp_digest
from app.settings import get_settings

log = structlog.get_logger("scout.tasks")


async def _do_geocode_backfill(*, batch_limit: int | None = None) -> dict:
    from app.services.geography import backfill_missing

    async with get_session_factory()() as session:
        return await backfill_missing(session, batch_limit=batch_limit)


async def geocode_backfill_task(*, batch_limit: int | None = None) -> dict:
    """Geocode conferences with no coordinates, as a tracked background job.

    This ran INLINE in the admin endpoint before: ~1 second per conference
    against Nominatim's rate limit, so a full backfill held one HTTP request
    open for ~12 minutes. In dev, editing any file mid-run made uvicorn's
    reload wait on that request to drain — the whole API refused connections
    until it finished. A 12-minute request is a job, not a response.
    """
    return await run_as_job(
        "geocode_backfill",
        _do_geocode_backfill,
        batch_limit=batch_limit,
    )


# ==========================================================================
# tasks.py
# ==========================================================================


async def run_as_job(
    kind: str,
    coro_factory: Callable[..., Awaitable[Any]],
    *,
    stats_extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute ``coro_factory(**kwargs)`` while tracking a row in
    ``app.ingest_jobs``.

    Returns a small dict describing the run: ``{ingest_job_id, status,
    duration_ms, stats}``. Exceptions are caught + recorded on the row +
    re-raised so the scheduler logs ``Job ... raised`` (and so callers in
    tests still see the error).
    """
    job_id = uuid.uuid4()
    bound = log.bind(job_kind=kind, ingest_job_id=str(job_id))
    bound.info("task.started")
    t0 = time.perf_counter()

    started_at = datetime.now(tz=UTC)
    stats_extra = stats_extra or {}

    # Open a session purely to create the tracking row. The actual work
    # opens its own session inside ``coro_factory`` (so a long task doesn't
    # hold a transaction open while it does CPU-heavy work).
    async with get_session_factory()() as session:
        row = IngestJob(
            id=job_id,
            kind=kind,
            status="running",
            started_at=started_at,
            stats=stats_extra,
        )
        session.add(row)
        await session.commit()

    try:
        result = await coro_factory(**kwargs)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        bound.error("task.failed", error=str(exc), duration_ms=duration_ms)
        async with get_session_factory()() as session:
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(
                    status="failed",
                    finished_at=datetime.now(tz=UTC),
                    error_text=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                    stats={**stats_extra, "duration_ms": duration_ms},
                )
            )
            await session.commit()
        raise

    duration_ms = int((time.perf_counter() - t0) * 1000)
    final_stats: dict[str, Any] = {**stats_extra, "duration_ms": duration_ms}
    if isinstance(result, dict):
        final_stats.update(result)

    async with get_session_factory()() as session:
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(
                status="complete",
                finished_at=datetime.now(tz=UTC),
                stats=final_stats,
            )
        )
        await session.commit()

    bound.info("task.completed", duration_ms=duration_ms, stats=final_stats)
    return {
        "ingest_job_id": str(job_id),
        "status": "complete",
        "duration_ms": duration_ms,
        "stats": final_stats,
    }


# ==========================================================================
# tasks.py
# ==========================================================================


async def _do_heartbeat() -> dict[str, str]:
    return {"alive": "true"}


async def heartbeat() -> dict[str, object]:
    """APScheduler-callable entry point."""
    return await run_as_job("heartbeat", _do_heartbeat)


# ==========================================================================
# tasks.py
# ==========================================================================


async def _do_scrape(*, source_id: str) -> dict[str, Any]:
    """Inner crawl runner — opens its own DB session."""
    async with get_session_factory()() as session:
        try:
            result = await run_crawl_source(session, UUID(source_id))
        except (SourceNotFoundError, SourceDisabledError):
            await session.rollback()
            raise
        await session.commit()
    return result.to_stats()


async def scrape_source_task(*, source_id: str) -> dict[str, Any]:
    """APScheduler-callable. Wraps the crawl in :func:`run_as_job` so an
    ``app.ingest_jobs`` row tracks the run."""
    return await run_as_job(
        "scrape_source",
        _do_scrape,
        source_id=source_id,
        stats_extra={"source_id": source_id},
    )


async def _do_poll() -> dict[str, Any]:
    """Find sources due for crawl + enqueue one scrape per."""
    enqueued: list[str] = []
    async with get_session_factory()() as session:
        # "Due" = enabled AND (never crawled OR last_crawled_at older than cadence).
        # cadence is stored as text (e.g. "1 day"); cast to interval inline.
        # Note: cadence text is validated at the schema layer against a
        # small allowlist of `<int> <unit>` shapes, so the cast is safe.
        stmt = (
            select(Source)
            .where(Source.enabled.is_(True))
            .where(
                sql_text(
                    "last_crawled_at IS NULL "
                    "OR last_crawled_at < now() - cast(crawl_cadence AS interval)"
                )
            )
        )
        result = await session.execute(stmt)
        for source in result.scalars():
            job_id = f"scrape-{source.id}"
            # Imported at call time: app/scheduler.py imports this module at
            # module scope to build ENQUEUEABLE, so importing it back here at
            # module scope is a cycle.
            from app.scheduler import enqueue_now

            enqueue_now(
                scrape_source_task,
                job_id=job_id,
                kwargs={"source_id": str(source.id)},
            )
            enqueued.append(str(source.id))
            log.info(
                "scrape.poll.enqueued",
                source_id=str(source.id),
                source_name=source.name,
            )
    return {"enqueued_source_count": len(enqueued), "source_ids": enqueued}


async def poll_sources_due_for_crawl() -> dict[str, Any]:
    """APScheduler-callable. Cron entry point — runs every 15 minutes via
    :func:`app.scheduler.register_jobs`."""
    return await run_as_job("scrape_poll", _do_poll)


# ==========================================================================
# tasks.py
# ==========================================================================


async def _do_parse(*, raw_page_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await parse_raw_page(session, UUID(raw_page_id))
        await session.commit()
    return result.to_stats()


async def parse_raw_page_task(*, raw_page_id: str) -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job` so each parse
    lands a typed row in ``app.ingest_jobs``."""
    return await run_as_job(
        "parse_raw_page",
        _do_parse,
        raw_page_id=raw_page_id,
        stats_extra={"raw_page_id": raw_page_id},
    )


# ==========================================================================
# tasks.py
# ==========================================================================


async def _do_discovery(
    *, prompt: str | None = None, max_results: int | None = None
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.discovery_enabled:
        log.info("discovery.task.disabled")
        return {"skipped": True, "reason": "discovery_enabled=false"}

    async with get_session_factory()() as session:
        result = await run_discovery(
            session,
            prompt=prompt or "",
            max_results=max_results,
        )
        await session.commit()
    return result.to_dict()


async def run_discovery_task(
    *, prompt: str | None = None, max_results: int | None = None
) -> dict[str, Any]:
    return await run_as_job(
        "run_discovery",
        _do_discovery,
        prompt=prompt,
        max_results=max_results,
    )


# ==========================================================================
# tasks.py
# ==========================================================================


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

        # Re-embed. embed_owner already clears this owner's chunks FOR THE
        # ACTIVE MODEL before writing, so there is nothing to delete here.
        #
        # There used to be a delete here, and it was unscoped: it dropped
        # every chunk for the conference regardless of embedding_model_id,
        # destroying the previous model's vectors that embeddings/pipeline.py
        # deliberately keeps so a model rollover can be rolled back. Two
        # places deleting the same rows by different rules, and the looser
        # one silently won whenever a conference was re-enriched.
        text = conference_embed_text(conf)
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
            except Exception as exc:
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
            "fit_score": match_stats.get("fit_score"),
            "speaker_score": match_stats.get("speaker_score"),
        }
    except Exception as exc:
        bound.warning("enrich_and_match.matcher_failed", error=str(exc))
        return {
            "ok": False,
            "enriched": enriched,
            "embedded": embedded,
            "reason": f"matcher_failed: {exc!s}",
        }


# ==========================================================================
# tasks.py
# ==========================================================================


async def _do_run_fit_match(*, conference_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        try:
            result = await run_fit_match(session, UUID(conference_id))
        except (ConferenceNotFoundError, ConferenceQuarantinedError):
            await session.rollback()
            raise
        await session.commit()
    return result.to_stats()


async def run_fit_match_task(*, conference_id: str) -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job`."""
    return await run_as_job(
        "run_fit_match",
        _do_run_fit_match,
        conference_id=conference_id,
        stats_extra={"conference_id": conference_id},
    )


async def _do_recompute_all() -> dict[str, Any]:
    """Process every non-quarantined conference inline with bounded
    concurrency.

    Previous version fanned each conference out as its OWN APScheduler
    job. With 583 conferences, that meant 583 jobs all firing in the
    event loop at once, each grabbing a DB session, and the SQLAlchemy
    pool (5 + 10 overflow = 15 max) exhausted in seconds → 564 timed
    out at QueuePool. The LLM semaphore couldn't help because the
    bottleneck was DB connections, not LLM calls.

    Now: one orchestrator task loops the conferences and runs them
    through an asyncio.Semaphore-bounded gather. Concurrency lives at
    the matcher-job level (default 4); each task acquires its own
    short-lived DB session inside _do_run_fit_match, returns it
    promptly, and the pool stays healthy. The LLM semaphore still
    applies inside each task for the actual LLM call.
    """
    import asyncio

    async with get_session_factory()() as session:
        rows = (
            await session.execute(select(Conference.id).where(Conference.status != "quarantined"))
        ).all()
    conf_ids = [str(cid) for (cid,) in rows]
    log.info("matcher.recompute_all.start", count=len(conf_ids))

    # Concurrency knob: keep below the DB pool ceiling (15) with headroom
    # for the rest of the app. 4 is safe; tune via the same setting that
    # gates LLM calls (llm_max_concurrent_calls) since both share an
    # operational story.

    cap = max(1, min(8, int(get_settings().llm_max_concurrent_calls)))
    sem = asyncio.Semaphore(cap)
    results = {"succeeded": 0, "failed": 0}

    async def _one(cid: str) -> None:
        async with sem:
            try:
                await _do_run_fit_match(conference_id=cid)
                results["succeeded"] += 1
            except Exception as exc:
                results["failed"] += 1
                log.warning(
                    "matcher.recompute_all.task_failed",
                    conference_id=cid,
                    error=str(exc)[:200],
                )

    # asyncio.gather schedules all tasks but the semaphore caps how many
    # actually proceed past `async with sem`. The rest park on the
    # semaphore without holding DB connections.
    await asyncio.gather(*(_one(cid) for cid in conf_ids))

    log.info(
        "matcher.recompute_all.done",
        total=len(conf_ids),
        succeeded=results["succeeded"],
        failed=results["failed"],
        concurrency_cap=cap,
    )
    return {
        "total": len(conf_ids),
        "succeeded": results["succeeded"],
        "failed": results["failed"],
        "concurrency_cap": cap,
    }


async def recompute_all_matches() -> dict[str, Any]:
    """APScheduler-callable. Fans out one ``run_fit_match_task`` per
    non-quarantined conference. Tracked as a single ingest_jobs row."""
    return await run_as_job("matcher_recompute_all", _do_recompute_all)


async def _do_rescore_stale() -> dict[str, Any]:
    """Rescore only the conferences with no match at the current version."""
    import asyncio

    async with get_session_factory()() as session:
        current = (
            select(Match.conference_id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
            .scalar_subquery()
        )
        rows = (
            await session.execute(
                select(Conference.id)
                .where(Conference.status != "quarantined")
                .where(Conference.id.not_in(current))
            )
        ).all()
    conf_ids = [str(cid) for (cid,) in rows]
    log.info(
        "matcher.rescore_stale.start",
        count=len(conf_ids),
        algorithm_version=ALGORITHM_VERSION,
    )
    if not conf_ids:
        return {"total": 0, "succeeded": 0, "failed": 0}

    cap = max(1, min(8, int(get_settings().llm_max_concurrent_calls)))
    sem = asyncio.Semaphore(cap)
    results = {"succeeded": 0, "failed": 0}

    async def _one(cid: str) -> None:
        async with sem:
            try:
                await _do_run_fit_match(conference_id=cid)
                results["succeeded"] += 1
            except Exception as exc:
                results["failed"] += 1
                log.warning(
                    "matcher.rescore_stale.task_failed",
                    conference_id=cid,
                    error=str(exc)[:200],
                )

    await asyncio.gather(*(_one(cid) for cid in conf_ids))
    return {"total": len(conf_ids), **results}


async def rescore_stale_matches() -> dict[str, Any]:
    """Bring conferences up to the current ALGORITHM_VERSION.

    Exists because bumping the version silently empties the app. Every read
    path joins matches on ``algorithm_version == ALGORITHM_VERSION``, so the
    moment that constant changes every stored row stops being visible: blank
    scores across the whole list, an empty dashboard, and 404s from
    GET /conferences/{id}/match. Nothing recovered from that automatically —
    ``_version.py`` claimed "the bump is what triggers a bulk recompute" and
    nothing did.

    Unlike ``recompute_all_matches`` this only touches conferences that have
    no row at the current version, so it is cheap to run on a timer and a
    no-op once the corpus has caught up. That matters: the judge runs on
    every conference it scores, so an unconditional daily rescore would be a
    real recurring spend.
    """
    return await run_as_job("matcher_rescore_stale", _do_rescore_stale)


# ==========================================================================
# tasks.py
# ==========================================================================


async def _do_build() -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await build_cfp_digest(session)
        await session.commit()
    return result.to_stats()


async def build_cfp_digest_task() -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job`."""
    return await run_as_job("build_cfp_digest", _do_build)


__all__ = [
    "build_cfp_digest_task",
    "enrich_and_match_task",
    "heartbeat",
    "parse_raw_page_task",
    "poll_sources_due_for_crawl",
    "recompute_all_matches",
    "rescore_stale_matches",
    "run_as_job",
    "run_discovery_task",
    "run_fit_match_task",
    "scrape_source_task",
]


# ==========================================================================
# talk upload — parse + extract as a tracked job
# ==========================================================================
#
# "Fill from document" used to run Docling + the LLM inside one HTTP
# request: ~50 blind seconds for the operator, and every proxy/router
# timeout between browser and worker had to be raised above it. As a job,
# the request returns a job id immediately, the UI polls real stages
# (queued → parsing → extracting), and a refresh mid-run loses nothing.


async def _update_upload_job(job_id: str, **values: Any) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            update(IngestJob).where(IngestJob.id == uuid.UUID(job_id)).values(**values)
        )
        await session.commit()


async def _merge_upload_stats(job_id: str, extra: dict[str, Any]) -> None:
    async with get_session_factory()() as session:
        row = await session.get(IngestJob, uuid.UUID(job_id))
        if row is None:
            return
        row.stats = {**(row.stats or {}), **extra}
        await session.commit()


async def talk_upload_extract_task(
    *, job_id: str, file_path: str, filename: str
) -> None:
    """Parse an uploaded talk document and extract fields, updating the
    tracking row's ``stats.stage`` as it goes. The extracted preview lands
    in ``stats.extracted`` for the poll endpoint to hand back."""
    from pathlib import Path

    from fastapi.concurrency import run_in_threadpool

    from app.services.pdf import parse_and_chunk
    from app.services.people import extract_talk_from_text

    path = Path(file_path)
    try:
        await _update_upload_job(
            job_id, status="running", started_at=datetime.now(tz=UTC)
        )
        await _merge_upload_stats(job_id, {"stage": "parsing"})

        if filename.lower().endswith(".txt"):
            full_text = path.read_bytes().decode("utf-8", errors="replace")
        else:
            parsed = await run_in_threadpool(parse_and_chunk, path)
            full_text = parsed.full_text

        await _merge_upload_stats(job_id, {"stage": "extracting"})
        async with get_session_factory()() as session:
            extracted = await extract_talk_from_text(db=session, full_text=full_text)
            # The LLM client stages its spend row on this session.
            await session.commit()

        await _merge_upload_stats(
            job_id, {"stage": "done", "extracted": extracted.model_dump()}
        )
        await _update_upload_job(
            job_id, status="complete", finished_at=datetime.now(tz=UTC)
        )
    except Exception as exc:
        log.warning(
            "talk_upload.failed", job_id=job_id, error=f"{type(exc).__name__}: {exc}"
        )
        await _merge_upload_stats(job_id, {"stage": "failed"})
        await _update_upload_job(
            job_id,
            status="failed",
            finished_at=datetime.now(tz=UTC),
            error_text=f"{type(exc).__name__}: {exc}",
        )
    finally:
        path.unlink(missing_ok=True)


async def messaging_upload_extract_task(
    *, job_id: str, file_path: str, filename: str, doc_kind: str
) -> None:
    """Messaging/GTM/roadmap document upload as a tracked job — same shape
    as talk_upload_extract_task. A real GTM PDF took 176s of Docling + LLM
    inside one HTTP request (three minutes of dead air), and a heavier one
    OOMKilled the API pod at 3Gi. The scheduler pod owns Docling now."""
    from pathlib import Path

    from fastapi.concurrency import run_in_threadpool

    from app.services.pdf import parse_and_chunk
    from app.services.positioning import extract_messaging_from_text

    path = Path(file_path)
    try:
        await _update_upload_job(
            job_id, status="running", started_at=datetime.now(tz=UTC)
        )
        await _merge_upload_stats(job_id, {"stage": "parsing"})
        parsed = await run_in_threadpool(parse_and_chunk, path)

        await _merge_upload_stats(job_id, {"stage": "extracting"})
        async with get_session_factory()() as session:
            preview = await extract_messaging_from_text(
                db=session, full_text=parsed.full_text, doc_kind=doc_kind
            )
            await session.commit()  # LLM spend row rides this session

        await _merge_upload_stats(
            job_id, {"stage": "done", "extracted": preview.model_dump()}
        )
        await _update_upload_job(
            job_id, status="complete", finished_at=datetime.now(tz=UTC)
        )
    except Exception as exc:
        log.warning(
            "messaging_upload.failed", job_id=job_id, error=f"{type(exc).__name__}: {exc}"
        )
        await _merge_upload_stats(job_id, {"stage": "failed"})
        await _update_upload_job(
            job_id,
            status="failed",
            finished_at=datetime.now(tz=UTC),
            error_text=f"{type(exc).__name__}: {exc}",
        )
    finally:
        path.unlink(missing_ok=True)
