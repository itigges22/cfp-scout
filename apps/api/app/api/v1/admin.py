"""The admin console: every operator-only endpoint.

WHAT THIS DOES
    Settings overrides, the LLM key and probe, embedding backfills,
    re-extraction, job history and retries, manual discovery runs, and
    manual matcher runs.

HOW IT CONNECTS
    Calls       services/settings_store.py, services/llm.py,
                services/embeddings.py, services/extraction.py,
                services/discovery.py, services/matcher.py,
                services/diagnostics.py
    Serves      /api/v1/admin/*

WORTH KNOWING
    Seven modules, one screen group, one prefix tree. Each keeps its own
    APIRouter because the prefixes differ; they are combined at the bottom.

    ``admin_discovery`` and ``admin_matcher`` both had a ``run_now`` and a
    ``run_now_async``. In one namespace the second pair shadowed the first,
    so they are now ``run_discovery_now`` / ``run_matcher_now``.

    The LLM API key is never read from config — it is entered here, after
    deployment, and stored as a setting override.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, or_, select

from app.db.models import (
    AppSettingOverride,
    Conference,
    DocumentChunk,
    IngestJob,
    LLMCall,
    Match,
    MessagingDocument,
    Sme,
    StrategicPillar,
    Talk,
)
from app.db.session import DbSession
from app.scheduler import enqueue_now, get_scheduler
from app.services import settings_store
from app.services.conferences import link_conference_series_orphans
from app.services.discovery import (
    FeedFilters,
    ingest_developers_events,
    run_discovery,
)
from app.services.embeddings import (
    chunk_text,
    embed_owner,
    get_active_embedding_model,
    similar_chunks,
)
from app.services.extraction import parse_raw_page
from app.services.llm import (
    BudgetExceeded,
    ChatMessage,
    ChatRequest,
    EmbeddingRequest,
    get_llm_client,
)
from app.services.matcher import ALGORITHM_VERSION, ConferenceNotFoundError, run_fit_match
from app.settings import (  # noqa: F401 — re-exported for callers
    SPECS,
    SettingGroup,
    SettingKind,
    Settings,
    SettingSpec,
    coerce_setting,
    get_settings,
)
from app.tasks import (
    build_cfp_digest_task,
    geocode_backfill_task,
    parse_raw_page_task,
    recompute_all_matches,
    run_discovery_task,
    run_fit_match_task,
)
from app.tasks import heartbeat as heartbeat_task

log = structlog.get_logger("scout.api.admin")


# ==========================================================================
# admin_llm.py
# ==========================================================================


_r_llm = APIRouter(prefix="/api/v1/admin/llm", tags=["admin.llm"])


@_r_llm.post("/test-chat")
async def test_chat(db: DbSession, prompt: str, purpose: str = "admin_test") -> dict:
    """Round-trip a chat call. With ``LLM_DRY_RUN=true`` returns a canned response."""
    log.info("admin.llm.test_chat", purpose=purpose, prompt_chars=len(prompt))
    try:
        resp = await get_llm_client().chat(
            ChatRequest(
                messages=[ChatMessage(role="user", content=prompt)],
                purpose=purpose,
            ),
            db=db,
        )
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    await db.commit()
    return resp.model_dump(mode="json")


@_r_llm.post("/test-embed")
async def test_embed(db: DbSession, text: str, purpose: str = "admin_test") -> dict:
    """Round-trip an embedding call. Returns the dimension + first few values
    so the response stays small."""
    log.info("admin.llm.test_embed", purpose=purpose, text_chars=len(text))
    try:
        resp = await get_llm_client().embed(
            EmbeddingRequest(texts=[text], purpose=purpose),
            db=db,
        )
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    await db.commit()
    vec = resp.vectors[0]
    return {
        "model": resp.model,
        "dimension": len(vec),
        "preview": vec[:5],
        "prompt_tokens": resp.prompt_tokens,
        "cost_usd": resp.cost_usd,
        "latency_ms": resp.latency_ms,
    }


@_r_llm.get("/stats")
async def stats(db: DbSession) -> dict:
    """Month-to-date + last-24h LLM usage summary.

    The /diagnostics page surfaces the same data in a real UI; this is
    a JSON aggregator for ad-hoc inspection.
    """
    now = datetime.now(tz=UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    day_start = now - timedelta(hours=24)

    async def _sum(since: datetime) -> dict:
        result = await db.execute(
            select(
                func.count(LLMCall.id),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
                func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens), 0),
            ).where(LLMCall.created_at >= since)
        )
        row = result.one()
        return {
            "calls": int(row[0]),
            "cost_usd": float(row[1]),
            "tokens": int(row[2]),
        }

    # Group purposes for the month
    by_purpose_q = await db.execute(
        select(
            LLMCall.purpose,
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
        )
        .where(LLMCall.created_at >= month_start)
        .group_by(LLMCall.purpose)
        .order_by(func.sum(LLMCall.cost_usd).desc())
    )
    by_purpose = [
        {"purpose": row[0], "calls": int(row[1]), "cost_usd": float(row[2])}
        for row in by_purpose_q.all()
    ]

    return {
        "month_to_date": await _sum(month_start),
        "last_24h": await _sum(day_start),
        "by_purpose_mtd": by_purpose,
    }


# ==========================================================================
# admin_embeddings.py
# ==========================================================================


_r_embeddings = APIRouter(prefix="/api/v1/admin/embeddings", tags=["admin.embeddings"])


class EmbedTextRequest(BaseModel):
    """Ad-hoc embed: writes nothing to vectors.document_chunks."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1)
    purpose: str = "admin_embed_text"


class EmbedOwnerRequest(BaseModel):
    """Persist chunks against a real owner. Idempotent (replaces prior chunks)."""

    model_config = ConfigDict(extra="forbid")
    owner_type: str = Field(
        ..., description="messaging / audience / conference / sme_bio / raw_page"
    )
    owner_id: UUID
    text: str
    purpose: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=1)
    owner_types: list[str] | None = None
    k: int = Field(5, ge=1, le=50)


@_r_embeddings.get("/model")
async def active_model(db: DbSession) -> dict:
    row = await get_active_embedding_model(db)
    return {
        "id": str(row.id),
        "name": row.name,
        "provider": row.provider,
        "dimension": row.dimension,
        "is_active": row.is_active,
    }


@_r_embeddings.get("/stats")
async def chunk_stats(db: DbSession) -> dict:
    """Chunk counts by owner_type, plus the active model info."""
    model_row = await get_active_embedding_model(db)
    result = await db.execute(
        select(DocumentChunk.owner_type, func.count(DocumentChunk.id))
        .group_by(DocumentChunk.owner_type)
        .order_by(DocumentChunk.owner_type)
    )
    by_type = [{"owner_type": row[0], "chunks": int(row[1])} for row in result.all()]
    total = sum(row["chunks"] for row in by_type)
    return {
        "active_model": {
            "id": str(model_row.id),
            "name": model_row.name,
            "dimension": model_row.dimension,
        },
        "total_chunks": total,
        "by_owner_type": by_type,
    }


@_r_embeddings.post("/embed-text")
async def embed_ad_hoc(db: DbSession, payload: EmbedTextRequest) -> dict:
    """Chunk + embed the input text WITHOUT writing to document_chunks.
    Useful for "what would Scout do with this string?" diagnostics."""
    chunks = chunk_text(payload.text)
    if not chunks:
        return {
            "chunks": [],
            "vectors": [],
            "note": "input was empty after normalisation",
        }


    response = await get_llm_client().embed(
        EmbeddingRequest(
            texts=[c.text for c in chunks],
            purpose=payload.purpose,
        ),
        db=db,
    )
    await db.commit()  # records the llm_calls row

    return {
        "model": response.model,
        "prompt_tokens": response.prompt_tokens,
        "cost_usd": response.cost_usd,
        "latency_ms": response.latency_ms,
        "chunks": [
            {
                "chunk_index": c.chunk_index,
                "token_count": c.token_count,
                "char_count": len(c.text),
                "text_preview": (c.text[:80] + "…") if len(c.text) > 80 else c.text,
                "vector_dimension": len(v),
                "vector_preview": v[:3],
            }
            for c, v in zip(chunks, response.vectors, strict=True)
        ],
    }


@_r_embeddings.post("/embed-owner")
async def embed_owner_admin(db: DbSession, payload: EmbedOwnerRequest) -> dict:
    """Embed text against a real owner_id. Replaces existing chunks. Idempotent."""
    log.info(
        "admin.embed_owner.invoked",
        owner_type=payload.owner_type,
        owner_id=str(payload.owner_id),
        chars=len(payload.text),
    )
    inserted = await embed_owner(
        db,
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        text=payload.text,
        purpose=payload.purpose or f"embed:{payload.owner_type}",
    )
    await db.commit()
    return {
        "owner_type": payload.owner_type,
        "owner_id": str(payload.owner_id),
        "chunks_inserted": inserted,
    }


@_r_embeddings.post("/search")
async def search(db: DbSession, payload: SearchRequest) -> dict:
    """Return top-k chunks similar to the query, optionally filtered by owner_type."""
    hits = await similar_chunks(
        db,
        query=payload.query,
        owner_types=payload.owner_types,
        k=payload.k,
        purpose="admin_search",
        bump_last_used=False,  # diagnostic searches shouldn't pollute decay
    )
    await db.commit()
    return {
        "query": payload.query,
        "k": payload.k,
        "hits": [
            {
                "id": str(h.chunk.id),
                "owner_type": h.chunk.owner_type,
                "owner_id": str(h.chunk.owner_id),
                "chunk_index": h.chunk.chunk_index,
                "similarity": round(h.similarity, 4),
                "text_preview": (
                    (h.chunk.text[:120] + "…")
                    if len(h.chunk.text) > 120
                    else h.chunk.text
                ),
                "token_count": h.chunk.token_count,
            }
            for h in hits
        ],
    }


# ==========================================================================
# admin_extraction.py
# ==========================================================================


_r_extraction = APIRouter(prefix="/api/v1/admin/extraction", tags=["admin.extraction"])


@_r_extraction.post("/parse-now/{raw_page_id}")
async def parse_now(db: DbSession, raw_page_id: UUID) -> dict:
    """Run the extraction synchronously and return the :class:`ParseResult`."""
    log.info("admin.extraction.parse_now", raw_page_id=str(raw_page_id))
    result = await parse_raw_page(db, raw_page_id)
    await db.commit()
    return result.to_stats()


@_r_extraction.post("/parse-now-async/{raw_page_id}", status_code=status.HTTP_202_ACCEPTED)
async def parse_now_async(raw_page_id: UUID) -> dict:
    """Enqueue the parse via the scheduler and return immediately."""
    job_id = enqueue_now(
        parse_raw_page_task,
        job_id=f"parse-{raw_page_id}",
        kwargs={"raw_page_id": str(raw_page_id)},
    )
    log.info("admin.extraction.parse_enqueued", raw_page_id=str(raw_page_id), job_id=job_id)
    return {"queued_job_id": job_id, "raw_page_id": str(raw_page_id)}


# ==========================================================================
# admin_jobs.py
# ==========================================================================


_r_jobs = APIRouter(prefix="/api/v1/admin/jobs", tags=["admin.jobs"])


_RATE_LIMIT_WINDOW_S = 30.0


_last_triggered: dict[str, float] = {}


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    last = _last_triggered.get(key, 0.0)
    if now - last < _RATE_LIMIT_WINDOW_S:
        wait = _RATE_LIMIT_WINDOW_S - (now - last)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Job {key!r} was triggered recently; try again in {wait:.1f}s.",
        )
    _last_triggered[key] = now


@_r_jobs.get("")
async def list_jobs() -> dict:
    """All registered (cron + ad-hoc-still-pending) jobs.

    APScheduler's view of the jobstore — not the run history. Use
    ``/runs`` for that.
    """
    scheduler = get_scheduler()
    if not scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "func": f"{job.func.__module__}.{job.func.__name__}",
                "trigger": str(job.trigger),
                "next_run_time": (job.next_run_time.isoformat() if job.next_run_time else None),
                "coalesce": job.coalesce,
                "max_instances": job.max_instances,
                "misfire_grace_time": job.misfire_grace_time,
            }
        )
    return {
        "running": True,
        "timezone": str(scheduler.timezone),
        "jobs": jobs,
    }


@_r_jobs.get("/runs")
async def list_runs(db: DbSession, limit: int = 50) -> dict:
    """Recent ``app.ingest_jobs`` rows — successes + failures.

    Filterable by passing ``?limit=N`` (default 50, hard-capped at 500).
    """
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    result = await db.execute(
        select(IngestJob).order_by(IngestJob.started_at.desc().nullslast()).limit(limit)
    )
    rows = result.scalars().all()
    return {
        "limit": limit,
        "runs": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "status": row.status,
                "started_at": _iso(row.started_at),
                "finished_at": _iso(row.finished_at),
                "duration_ms": (row.stats or {}).get("duration_ms"),
                "stats": row.stats,
                "error_text": row.error_text,
            }
            for row in rows
        ],
    }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


@_r_jobs.post("/heartbeat/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_heartbeat() -> dict:
    """Fire the heartbeat task immediately (in addition to its 10-min cron).

    Useful to verify the scheduler from curl without waiting for the next
    scheduled fire. Rate-limited to one trigger per 30s per job-id.
    """
    _check_rate_limit("heartbeat")
    job_id = enqueue_now(heartbeat_task, job_id="heartbeat-manual")
    log.info("admin.jobs.heartbeat_triggered", job_id=job_id)
    return {"queued_job_id": job_id, "kind": "heartbeat"}


@_r_jobs.post("/build_cfp_digest/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_cfp_digest() -> dict:
    """Fire the CFP digest builder immediately.

    Rate-limited to one trigger per 30s. Useful for verifying the digest
    after edits to ``cfp_deadlines`` without waiting for the 09:00 cron.
    """
    _check_rate_limit("cfp_digest")
    job_id = enqueue_now(build_cfp_digest_task, job_id="cfp-digest-manual")
    log.info("admin.jobs.cfp_digest_triggered", job_id=job_id)
    return {"queued_job_id": job_id, "kind": "build_cfp_digest"}


# ==========================================================================
# admin_discovery.py
# ==========================================================================


_r_discovery = APIRouter(prefix="/api/v1/admin/discovery", tags=["admin.discovery"])


class DiscoveryRunRequest(BaseModel):
    prompt: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "Override the default template prompt for this run. If omitted, "
            "uses `settings.discovery_template_prompt`."
        ),
    )
    max_results: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Override results-per-query for this run.",
    )


@_r_discovery.post("/run-now")
async def run_discovery_now(
    db: DbSession,
    body: Annotated[DiscoveryRunRequest, Body()] = DiscoveryRunRequest(),
) -> dict:
    """Run discovery synchronously and return the full result."""
    settings = get_settings()
    if not settings.discovery_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="discovery_enabled is false; toggle it in /settings/tunables",
        )
    log.info(
        "admin.discovery.run_discovery_now",
        prompt_chars=len(body.prompt or settings.discovery_template_prompt),
        max_results=body.max_results,
    )
    result = await run_discovery(
        db,
        prompt=body.prompt or "",
        max_results=body.max_results,
    )
    return result.to_dict()


@_r_discovery.post("/run-now-async", status_code=status.HTTP_202_ACCEPTED)
async def run_discovery_now_async(
    body: Annotated[DiscoveryRunRequest, Body()] = DiscoveryRunRequest(),
) -> dict:
    settings = get_settings()
    if not settings.discovery_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="discovery_enabled is false; toggle it in /settings/tunables",
        )


    job_id = enqueue_now(
        run_discovery_task,
        job_id="discovery-run-manual",
        kwargs={
            "prompt": body.prompt,
            "max_results": body.max_results,
        },
    )
    return {"queued_job_id": job_id}


class FeedIngestRequest(BaseModel):
    only_ai: bool = Field(
        default=False,
        description=(
            "Filter the feed to keyword-matching events only. Off by "
            "default: measured against the live feed this filter dropped "
            "375 of 801 future events, including conferences for our own "
            "projects. Turn on only if the list genuinely floods."
        ),
    )
    future_only: bool = Field(
        default=True,
        description="Skip events whose start_date is in the past.",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=10000,
        description="Cap how many filtered events get persisted this run. Null = unlimited.",
    )


@_r_discovery.post("/ingest-feed")
async def ingest_feed(
    db: DbSession,
    body: Annotated[FeedIngestRequest, Body()] = FeedIngestRequest(),
) -> dict:
    """Pull the developers.events JSON feed and create Conference rows
    for every matching event. No LLM extraction — the feed is already
    structured. Way cheaper than the scrape+extract path."""
    result = await ingest_developers_events(
        db,
        filters=FeedFilters(
            only_ai=body.only_ai,
            future_only=body.future_only,
            limit=body.limit,
        ),
        actor_label="ingest_feed_manual",
    )
    return result.to_dict()


class GeocodeBackfillRequest(BaseModel):
    batch_limit: int | None = Field(
        default=None,
        ge=1,
        le=2000,
        description=(
            "Stop after geocoding this many rows. Null = walk every row with "
            "a city and no coordinates yet. The Nominatim policy is 1 req/sec, "
            "so 500 rows ≈ 9 minutes."
        ),
    )


@_r_discovery.post("/geocode-backfill", status_code=status.HTTP_202_ACCEPTED)
async def geocode_backfill(
    body: Annotated[GeocodeBackfillRequest, Body()] = GeocodeBackfillRequest(),
) -> dict:
    """Queue the geocode backfill and return immediately.

    This used to await the whole backfill in-request — ~1s per conference
    for Nominatim's rate limit, ~12 minutes for a full pass. Now it is a
    tracked job like discovery: watch it under Diagnostics → jobs, or in
    app.ingest_jobs (kind='geocode_backfill'). The fixed job id means
    clicking twice collapses into one run instead of two competing passes.
    """
    job_id = enqueue_now(
        geocode_backfill_task,
        job_id="geocode-backfill-manual",
        kwargs={"batch_limit": body.batch_limit},
    )
    return {"queued_job_id": job_id, "kind": "geocode_backfill"}


# ==========================================================================
# admin_matcher.py
# ==========================================================================


_r_matcher = APIRouter(prefix="/api/v1/admin/matcher", tags=["admin.matcher"])


@_r_matcher.post("/run-now/{conference_id}")
async def run_matcher_now(db: DbSession, conference_id: UUID) -> dict:
    """Run the matcher synchronously and return the MatchResult.

    A conference id that does not exist is a 404. It used to be a 500:
    ``run_fit_match`` raises ``ConferenceNotFoundError``, nothing mapped
    it, and the generic handler turned an ordinary "you asked for a row
    that is not there" into an unhandled-exception page with a traceback
    in the logs.
    """
    log.info("admin.matcher.run_matcher_now", conference_id=str(conference_id))
    try:
        result = await run_fit_match(db, conference_id)
    except ConferenceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await db.commit()
    return result.to_stats()


@_r_matcher.post("/run-now-async/{conference_id}", status_code=status.HTTP_202_ACCEPTED)
async def run_matcher_now_async(conference_id: UUID) -> dict:
    job_id = enqueue_now(
        run_fit_match_task,
        job_id=f"match-{conference_id}",
        kwargs={"conference_id": str(conference_id)},
    )
    log.info("admin.matcher.run_enqueued", conference_id=str(conference_id), job_id=job_id)
    return {"queued_job_id": job_id, "conference_id": str(conference_id)}


@_r_matcher.get("/freshness")
async def matcher_freshness(db: DbSession) -> dict:
    """Are the stored scores older than the corpus they were computed from?

    Scores are frozen at compute time. Uploading a messaging document,
    enriching a pillar or editing an SME changes what the matcher WOULD
    say, but nothing rescored automatically and nothing told the operator
    — the numbers just sat there looking current. This is the check the
    UI polls to say "your data changed, these scores predate it".

    Progress needs no bookkeeping in the task: a rescore stamps
    ``matches.computed_at`` per conference, so "rows newer than the
    running job's start" IS the done-count.
    """
    corpus_times = []
    for model in (MessagingDocument, StrategicPillar, Sme, Talk):
        t = (await db.execute(select(func.max(model.updated_at)))).scalar()
        if t is not None:
            corpus_times.append(t)
    # Matcher-relevant SETTINGS count as corpus too. Editing a gate or a
    # weight changes what every stored status/score means, but the first
    # version of this check only watched the four content tables — so an
    # operator could move match_m_gate and the banner would insist
    # everything was fresh. Filtered by prefix so a log-level edit does
    # not nag the whole team to rescore.
    matcher_prefixes = (
        "match_", "sme_w_", "boost_", "penalty_", "decay_",
        "chunk_", "matcher_", "prompt_", "operator_profile",
    )
    t = (
        await db.execute(
            select(func.max(AppSettingOverride.updated_at)).where(
                or_(*[AppSettingOverride.name.startswith(p_) for p_ in matcher_prefixes])
            )
        )
    ).scalar()
    if t is not None:
        corpus_times.append(t)
    corpus_changed_at = max(corpus_times) if corpus_times else None

    total_scored = (
        await db.execute(
            select(func.count()).select_from(Match).where(
                Match.algorithm_version == ALGORITHM_VERSION
            )
        )
    ).scalar_one()
    stale_count = 0
    if corpus_changed_at is not None:
        stale_count = (
            await db.execute(
                select(func.count()).select_from(Match).where(
                    Match.algorithm_version == ALGORITHM_VERSION,
                    Match.computed_at < corpus_changed_at,
                )
            )
        ).scalar_one()

    job = (
        await db.execute(
            select(IngestJob)
            .where(
                IngestJob.kind.in_(["matcher_recompute_all", "matcher_rescore_stale"]),
                IngestJob.status == "running",
            )
            .order_by(IngestJob.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    progress = None
    if job is not None and job.started_at is not None:
        done = (
            await db.execute(
                select(func.count()).select_from(Match).where(
                    Match.algorithm_version == ALGORITHM_VERSION,
                    Match.computed_at >= job.started_at,
                )
            )
        ).scalar_one()
        total = (
            await db.execute(
                select(func.count()).select_from(Conference).where(
                    Conference.status != "quarantined"
                )
            )
        ).scalar_one()
        progress = {"done": done, "total": total}

    return {
        "corpus_changed_at": corpus_changed_at.isoformat() if corpus_changed_at else None,
        "total_scored": total_scored,
        "stale_count": stale_count,
        "running": job is not None,
        "progress": progress,
    }


@_r_matcher.post("/recompute-all", status_code=status.HTTP_202_ACCEPTED)
async def recompute_all() -> dict:
    """Enqueue one matcher run per non-quarantined conference."""
    job_id = enqueue_now(
        recompute_all_matches,
        job_id="matcher_recompute_all_manual",
    )
    log.info("admin.matcher.recompute_all", job_id=job_id)
    return {"queued_job_id": job_id, "algorithm_version": ALGORITHM_VERSION}


@_r_matcher.get("/matches/recent")
async def recent_matches(db: DbSession, limit: int = Query(default=50, ge=1, le=500)) -> dict:
    rows = (
        (await db.execute(select(Match).order_by(Match.computed_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "limit": limit,
        "matches": [
            {
                "id": str(m.id),
                "conference_id": str(m.conference_id),
                "algorithm_version": m.algorithm_version,
                "fit_score": round(float(m.fit_score), 4),
                "speaker_score": round(float(m.speaker_score), 4),
                "overall_score": round(float(m.overall_score), 4),
                "recommended_sme_ids": [str(s) for s in m.recommended_sme_ids],
                "rationale_text_preview": (m.rationale_text or "")[:200],
                "computed_at": m.computed_at.isoformat() if m.computed_at else None,
            }
            for m in rows
        ],
    }


@_r_matcher.post("/link-conference-series")
async def link_conference_series(db: DbSession) -> dict:
    """Attach conferences with no series to the series they belong to.

    Identity comes from services/conferences/series_identity.py — the same rule the
    matcher uses, so this cannot disagree with what the matcher believes.
    No thresholds to tune: two names either share a series or they do not.
    Returns: {linked, skipped}.
    """

    log.info("admin.matcher.link_conference_series")
    result = await link_conference_series_orphans(db)
    await db.commit()
    return result.to_dict()


# ==========================================================================
# admin_settings.py
# ==========================================================================


_BY_NAME: dict[str, SettingSpec] = {sp.name: sp for sp in SPECS}


_r_settings = APIRouter(prefix="/api/v1/admin/settings", tags=["admin.settings"])


class SettingValue(BaseModel):
    spec: SettingSpec
    value: Any  # masked for secrets
    masked: bool = False
    is_overridden: bool = False
    overridden_at: str | None = None
    actor_label: str | None = None


class SettingsResponse(BaseModel):
    items: list[SettingValue]


def _mask(name: str, raw: Any) -> tuple[Any, bool]:
    """Return (display_value, masked). Show last 4 chars for non-empty
    secrets so users can sanity-check they have the right key without
    leaking it."""
    if not raw:
        return ("", False)
    s = str(raw)
    if len(s) <= 4:
        return ("***", True)
    return (f"***{s[-4:]}", True)


@_r_settings.get("", response_model=SettingsResponse)
async def list_settings(db: DbSession) -> SettingsResponse:
    settings = get_settings()
    from sqlalchemy import select as _sel


    rows = (await db.execute(_sel(AppSettingOverride))).scalars().all()
    overrides_meta = {r.name: (r.updated_at, r.actor_label) for r in rows}

    items: list[SettingValue] = []
    for spec in SPECS:
        raw_value = getattr(settings, spec.name, None)
        if hasattr(raw_value, "get_secret_value"):
            raw_value = raw_value.get_secret_value()
        if spec.kind == "secret":
            display, masked = _mask(spec.name, raw_value)
        else:
            display, masked = raw_value, False
        meta = overrides_meta.get(spec.name)
        items.append(
            SettingValue(
                spec=spec,
                value=display,
                masked=masked,
                is_overridden=spec.name in overrides_meta,
                overridden_at=meta[0].isoformat() if meta else None,
                actor_label=meta[1] if meta else None,
            )
        )
    return SettingsResponse(items=items)


class PatchRequest(BaseModel):
    """Partial update. Keys must be in ``SPECS``."""

    model_config = ConfigDict(extra="allow")

    actor_label: str = "admin"


class PatchResponse(BaseModel):
    updated: list[str]
    restart_required_for: list[str]
    items: list[SettingValue]


@_r_settings.patch("", response_model=PatchResponse)
async def patch_settings(db: DbSession, payload: PatchRequest) -> PatchResponse:
    """Apply a partial update. Unknown keys → 400. Values that would
    break a Settings validator (e.g. weights not summing to 1.0) → 422.
    """
    raw = payload.model_dump()
    actor_label = str(raw.pop("actor_label", "admin"))[:120]

    unknown = [k for k in raw if k not in _BY_NAME]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown setting names: {sorted(unknown)}",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no settings provided",
        )

    coerced: dict[str, Any] = {}
    for name, value in raw.items():
        # coerce_setting raises ValueError (not HTTPException) so the
        # non-HTTP callers can use it without depending on FastAPI. The
        # HTTP translation belongs here, at the boundary.
        try:
            coerced[name] = coerce_setting(_BY_NAME[name], value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    # Validate the FULL settings shape with the new values applied. This
    # catches Settings-level invariants like "matcher weights must sum to
    # 1.0" that no single PATCH could verify in isolation.
    candidate = {**settings_store.current(), **coerced}
    try:
        Settings(**candidate)  # type: ignore[arg-type]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"settings validator rejected the patch: {exc}",
        ) from exc

    # Persist + register each override.
    for name, value in coerced.items():
        await settings_store.upsert(
            db,
            name=name,
            value=value,
            actor_label=actor_label,
        )
    await db.commit()
    get_settings.cache_clear()

    restart_keys = [name for name in coerced if _BY_NAME[name].restart_required]
    log.info(
        "admin.settings.patched",
        names=list(coerced),
        actor=actor_label,
        restart_required=restart_keys,
    )

    # Build the response payload via the same shape as GET.
    response = await list_settings(db)
    return PatchResponse(
        updated=list(coerced),
        restart_required_for=restart_keys,
        items=response.items,
    )


@_r_settings.delete("/{name}")
async def reset_setting(db: DbSession, name: str) -> dict:
    if name not in _BY_NAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown setting: {name}",
        )
    deleted = await settings_store.remove(db, name=name)
    await db.commit()
    get_settings.cache_clear()
    return {"name": name, "deleted": deleted}


class SettingsBackup(BaseModel):
    """The export shape. Includes secret values in plain text.

    Treat the file as sensitive — it contains the LLM API key. Save with
    chmod 600, don't commit to git, don't share in chat.
    """

    scout_version: str = "0.1.0"
    exported_at: str
    warning: str = (
        "Contains secret API keys in plain text. Store with chmod 600, "
        "never commit to git, never share."
    )
    settings: dict[str, Any]


@_r_settings.get("/export", response_model=SettingsBackup)
async def export_settings(db: DbSession) -> SettingsBackup:
    """Snapshot every known setting (including secrets) for backup / move.

    The returned JSON is a full restore source: every key in `Settings` that
    has a registered SettingSpec is included with its current effective value
    (env default merged with active override). Secrets are emitted in plain
    text — the export is intended for the operator's local disk, not for
    sharing.
    """
    from datetime import UTC, datetime

    s = get_settings()
    payload: dict[str, Any] = {}
    for spec in SPECS:
        raw = getattr(s, spec.name, None)
        # Unwrap SecretStr so the JSON file is round-trip importable.
        if isinstance(raw, SecretStr):
            payload[spec.name] = raw.get_secret_value()
        else:
            payload[spec.name] = raw
    log.warning(
        "admin.settings.exported",
        n_keys=len(payload),
        includes_secrets=True,
    )
    return SettingsBackup(
        exported_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        settings=payload,
    )


class SettingsImportRequest(BaseModel):
    settings: dict[str, Any]
    actor_label: str = Field(default="import", max_length=120)
    skip_unknown: bool = Field(
        default=True,
        description=(
            "If true, silently skip keys not in the current settings spec "
            "(e.g. a setting renamed since the export). If false, 400 on "
            "unknown keys."
        ),
    )


class SettingsImportResponse(BaseModel):
    imported: list[str]
    skipped: list[str]
    restart_required_for: list[str]


@_r_settings.post("/import", response_model=SettingsImportResponse)
async def import_settings(
    db: DbSession,
    payload: SettingsImportRequest,
) -> SettingsImportResponse:
    """Apply a settings backup. Idempotent — re-importing the same file is
    a no-op. Existing overrides for keys not in the import are NOT touched
    (use DELETE /{name} or PATCH to undo individual settings)."""
    incoming = dict(payload.settings or {})
    if not incoming:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="settings payload is empty",
        )

    unknown = [k for k in incoming if k not in _BY_NAME]
    if unknown and not payload.skip_unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown settings: {sorted(unknown)}",
        )

    coerced: dict[str, Any] = {}
    skipped: list[str] = list(unknown)
    for name, value in incoming.items():
        if name not in _BY_NAME:
            continue
        if value is None:
            # Treat null as "leave alone" — different from PATCH's strictness.
            skipped.append(name)
            continue
        try:
            coerced[name] = coerce_setting(_BY_NAME[name], value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    # Validate the full Settings shape with everything applied. Catches
    # cross-field invariants like "matcher weights must sum to 1.0".
    candidate = {**settings_store.current(), **coerced}
    try:
        Settings(**candidate)  # type: ignore[arg-type]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"settings validator rejected the import: {exc}",
        ) from exc

    for name, value in coerced.items():
        await settings_store.upsert(
            db, name=name, value=value, actor_label=payload.actor_label
        )
    await db.commit()
    get_settings.cache_clear()

    restart_keys = [
        name for name in coerced if _BY_NAME[name].restart_required
    ]
    log.info(
        "admin.settings.imported",
        imported=list(coerced),
        skipped=skipped,
        actor=payload.actor_label,
        restart_required=restart_keys,
    )
    return SettingsImportResponse(
        imported=sorted(coerced),
        skipped=sorted(set(skipped)),
        restart_required_for=restart_keys,
    )


router = APIRouter()
for _sub in (_r_llm, _r_embeddings, _r_extraction, _r_jobs, _r_discovery, _r_matcher, _r_settings):
    router.include_router(_sub)
