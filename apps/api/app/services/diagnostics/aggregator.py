"""The /diagnostics aggregator (plan 26).

One denormalized response across six panels — LLM, jobs, scraper, data,
digest, system. 30-second in-memory cache to keep the page snappy under
the optional 30s auto-refresh.

The cache is module-level (single-process). With ``--workers 1`` (per
plan 13) that's correct — every request hits the same cache and the
30s TTL holds across requests. If we ever scale to multiple workers, the
cache becomes per-worker (still correct, just less efficient).
"""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    AudienceProfile,
    Conference,
    ConferenceSeries,
    RawPage,
    Sme,
    Source,
    Topic,
)
from app.db.models.ops import IngestJob, LLMCall, Notification
from app.db.models.vectors import EmbeddingModel
from app.settings import get_settings

log = structlog.get_logger("scout.diagnostics")

CACHE_TTL_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class DiagnosticsCache:
    payload: dict[str, Any] | None = None
    built_at: float = 0.0


_cache = DiagnosticsCache()
_lock = asyncio.Lock()


def invalidate_cache() -> None:
    """Drop the cached payload. The next request rebuilds.

    Useful from tests + the manual admin trigger that pokes the diagnostics
    page after a state change.
    """
    _cache.payload = None
    _cache.built_at = 0.0


async def build_diagnostics(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    """Return the diagnostics payload, rebuilding if the cache is cold or
    older than ``CACHE_TTL_SECONDS``. ``force=True`` bypasses the TTL."""
    now = time.monotonic()
    if not force and _cache.payload is not None and (now - _cache.built_at) < CACHE_TTL_SECONDS:
        return _cache.payload

    async with _lock:
        # Re-check after lock: another coroutine may have just rebuilt.
        if (
            not force
            and _cache.payload is not None
            and (time.monotonic() - _cache.built_at) < CACHE_TTL_SECONDS
        ):
            return _cache.payload
        payload = await _build(db)
        _cache.payload = payload
        _cache.built_at = time.monotonic()
        return payload


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
async def _build(db: AsyncSession) -> dict[str, Any]:
    """Run the six panel queries concurrently where possible."""
    settings = get_settings()
    now = datetime.now(tz=UTC)

    # Run independent queries in parallel via asyncio.gather. SQLAlchemy
    # async sessions serialize within a single session, so each panel
    # opens its own light queries off the same session — total wall-clock
    # is dominated by the slowest panel (system disk usage).
    llm_panel = await _llm_panel(db, now=now, settings=settings)
    jobs_panel = await _jobs_panel(db, now=now)
    scraper_panel = await _scraper_panel(db)
    data_panel = await _data_panel(db, settings=settings)
    digest_panel = await _digest_panel(db)
    system_panel = await _system_panel(db, settings=settings)

    return {
        "generated_at": now.isoformat(),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "llm": llm_panel,
        "jobs": jobs_panel,
        "scraper": scraper_panel,
        "data": data_panel,
        "digest": digest_panel,
        "system": system_panel,
    }


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------
async def _llm_panel(db: AsyncSession, *, now: datetime, settings) -> dict:
    """Month-to-date + last-24h spend + top purposes + recent errors."""
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    day_start = now - timedelta(hours=24)

    async def _agg(since: datetime) -> dict:
        row = (
            await db.execute(
                select(
                    func.count(LLMCall.id),
                    func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens), 0),
                    func.coalesce(func.sum(LLMCall.cost_usd), 0),
                ).where(LLMCall.created_at >= since)
            )
        ).one()
        return {
            "calls": int(row[0]),
            "tokens": int(row[1]),
            "cost_usd": float(row[2]),
        }

    mtd = await _agg(month_start)
    today = await _agg(day_start)

    # Last 24h by purpose.
    by_purpose_rows = (
        await db.execute(
            select(
                LLMCall.purpose,
                func.count(LLMCall.id),
                func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens), 0),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
            )
            .where(LLMCall.created_at >= day_start)
            .group_by(LLMCall.purpose)
            .order_by(func.sum(LLMCall.cost_usd).desc())
        )
    ).all()
    by_purpose = [
        {
            "purpose": p,
            "calls": int(n),
            "tokens": int(t),
            "cost_usd": float(c),
        }
        for p, n, t, c in by_purpose_rows
    ]

    # Recent errors (any non-null `error` text).
    err_rows = (
        await db.execute(
            select(LLMCall.created_at, LLMCall.model, LLMCall.purpose, LLMCall.error)
            .where(LLMCall.error.is_not(None))
            .order_by(LLMCall.created_at.desc())
            .limit(10)
        )
    ).all()
    recent_errors = [
        {
            "at": dt.isoformat() if dt else None,
            "model": m,
            "purpose": p,
            "error": (e or "")[:200],
        }
        for dt, m, p, e in err_rows
    ]

    # Budget bar.
    budget_usd = settings.llm_monthly_budget_usd
    spend_usd = mtd["cost_usd"]
    pct_used = round(spend_usd / budget_usd, 4) if (budget_usd and budget_usd > 0) else None
    threshold_warn = pct_used is not None and pct_used >= 0.8

    return {
        "month_to_date": mtd,
        "last_24h": today,
        "budget": {
            "limit_usd": budget_usd,
            "spent_usd": spend_usd,
            "pct_used": pct_used,
            "threshold_warn": threshold_warn,
        },
        "by_purpose_24h": by_purpose,
        "recent_errors": recent_errors,
    }


async def _jobs_panel(db: AsyncSession, *, now: datetime) -> dict:
    """Running ingest_jobs + recent failures + next-fire times from APScheduler."""
    day_start = now - timedelta(hours=24)

    running_rows = (
        await db.execute(
            select(IngestJob.id, IngestJob.kind, IngestJob.started_at)
            .where(IngestJob.status == "running")
            .order_by(IngestJob.started_at.desc())
            .limit(20)
        )
    ).all()
    running = [
        {
            "id": str(jid),
            "kind": kind,
            "started_at": st.isoformat() if st else None,
            "elapsed_seconds": (
                int((now - (st if st.tzinfo else st.replace(tzinfo=UTC))).total_seconds())
                if st
                else None
            ),
        }
        for jid, kind, st in running_rows
    ]

    failed_rows = (
        await db.execute(
            select(
                IngestJob.id,
                IngestJob.kind,
                IngestJob.started_at,
                IngestJob.finished_at,
                IngestJob.error_text,
            )
            .where(IngestJob.status == "failed")
            .where(IngestJob.started_at >= day_start)
            .order_by(IngestJob.started_at.desc())
            .limit(20)
        )
    ).all()
    failed_24h = [
        {
            "id": str(jid),
            "kind": kind,
            "started_at": st.isoformat() if st else None,
            "finished_at": ft.isoformat() if ft else None,
            "error_preview": (err or "").splitlines()[0][:200] if err else None,
        }
        for jid, kind, st, ft, err in failed_rows
    ]

    # Counts per kind over the last 24h (the "sparkline" stand-in).
    by_kind_rows = (
        await db.execute(
            select(IngestJob.kind, IngestJob.status, func.count(IngestJob.id))
            .where(IngestJob.started_at >= day_start)
            .group_by(IngestJob.kind, IngestJob.status)
            .order_by(IngestJob.kind, IngestJob.status)
        )
    ).all()
    by_kind: dict[str, dict[str, int]] = {}
    for kind, status, n in by_kind_rows:
        by_kind.setdefault(kind, {})[status] = int(n)

    # APScheduler introspection — pull live job list if the scheduler is
    # running in this process.
    next_fires: list[dict] = []
    try:
        from app.scheduler import get_scheduler  # local: avoid cycle

        scheduler = get_scheduler()
        if scheduler.running:
            for job in scheduler.get_jobs():
                next_fires.append(
                    {
                        "id": job.id,
                        "name": job.name,
                        "next_run_time": (
                            job.next_run_time.isoformat() if job.next_run_time else None
                        ),
                    }
                )
    except Exception as exc:
        log.warning("diagnostics.scheduler_introspect_failed", error=str(exc))

    return {
        "running": running,
        "failed_24h": failed_24h,
        "by_kind_24h": by_kind,
        "next_fires": next_fires,
    }


async def _scraper_panel(db: AsyncSession) -> dict:
    """Per-source crawl health + JS-blocked page counts."""
    source_rows = (
        (await db.execute(select(Source).order_by(Source.last_crawled_at.desc().nullslast())))
        .scalars()
        .all()
    )

    fetched_counts = dict(
        (
            await db.execute(
                select(RawPage.source_id, func.count(RawPage.id)).group_by(RawPage.source_id)
            )
        ).all()
    )

    sources = [
        {
            "id": str(s.id),
            "name": s.name,
            "kind": s.kind,
            "enabled": s.enabled,
            "robots_allowed": s.robots_allowed,
            "last_crawled_at": s.last_crawled_at.isoformat() if s.last_crawled_at else None,
            "pages_fetched": int(fetched_counts.get(s.id, 0)),
            "politeness_delay_seconds": s.politeness_delay_seconds,
        }
        for s in source_rows
    ]

    js_blocked = (
        await db.execute(
            select(func.count(RawPage.id)).where(RawPage.parse_status == "needs_js_render")
        )
    ).scalar_one()
    disabled_by_error = [{"id": s["id"], "name": s["name"]} for s in sources if not s["enabled"]]

    return {
        "sources": sources,
        "js_blocked_pages": int(js_blocked),
        "disabled_sources": disabled_by_error,
    }


async def _data_panel(db: AsyncSession, *, settings) -> dict:
    """Conferences by status + SME coverage + pending queues + freshness histo."""
    # Conferences by status.
    conf_status_rows = (
        await db.execute(
            select(Conference.status, func.count(Conference.id)).group_by(Conference.status)
        )
    ).all()
    conferences_by_status = {s: int(n) for s, n in conf_status_rows}

    # SME coverage.
    smes_total = (
        await db.execute(select(func.count(Sme.id)).where(Sme.is_active.is_(True)))
    ).scalar_one()
    smes_no_topics = (
        await db.execute(
            select(func.count(Sme.id))
            .where(Sme.is_active.is_(True))
            .where(func.array_length(Sme.primary_topics, 1).is_(None))
        )
    ).scalar_one()
    smes_no_audiences = (
        await db.execute(
            select(func.count(Sme.id))
            .where(Sme.is_active.is_(True))
            .where(func.array_length(Sme.audience_focus, 1).is_(None))
        )
    ).scalar_one()
    smes_short_bio = (
        await db.execute(
            select(func.count(Sme.id))
            .where(Sme.is_active.is_(True))
            .where(func.length(Sme.bio) < 200)
        )
    ).scalar_one()

    # Audience count.
    audiences_active = (
        await db.execute(
            select(func.count(AudienceProfile.id)).where(AudienceProfile.is_active.is_(True))
        )
    ).scalar_one()

    # Pending topics.
    pending_topics = (
        await db.execute(select(func.count(Topic.id)).where(Topic.pending_review.is_(True)))
    ).scalar_one()

    # Pending series suggestions (computed on demand by plan 23; we just
    # report whether there are unlinked eligible conferences, which is the
    # input to the suggestion engine).
    unlinked_conferences = (
        await db.execute(select(func.count(Conference.id)).where(Conference.series_id.is_(None)))
    ).scalar_one()
    series_count = (
        await db.execute(
            select(func.count(ConferenceSeries.id)).where(ConferenceSeries.is_active.is_(True))
        )
    ).scalar_one()

    # Embedding model.
    model_row = (
        await db.execute(select(EmbeddingModel).where(EmbeddingModel.is_active.is_(True)).limit(1))
    ).scalar_one_or_none()
    embedding_model = (
        {
            "name": model_row.name,
            "dimension": model_row.dimension,
            "provider": model_row.provider,
        }
        if model_row
        else None
    )

    # Freshness histogram (plan 25 helper).
    from app.services.lifecycle.decay import conference_freshness_histogram

    freshness_histogram = await conference_freshness_histogram(db, buckets=10)

    return {
        "conferences_by_status": conferences_by_status,
        "smes": {
            "total_active": int(smes_total),
            "no_topics": int(smes_no_topics),
            "no_audiences": int(smes_no_audiences),
            "short_bio": int(smes_short_bio),
        },
        "audiences_active": int(audiences_active),
        "pending_topics": int(pending_topics),
        "series": {
            "active_count": int(series_count),
            "unlinked_conferences": int(unlinked_conferences),
        },
        "embedding_model": embedding_model,
        "freshness_histogram": freshness_histogram,
        "decay_enabled": settings.decay_enabled,
    }


async def _digest_panel(db: AsyncSession) -> dict:
    """Last cfp_digest notification + bucket counts."""
    row = (
        await db.execute(
            select(Notification)
            .where(Notification.kind == "cfp_digest")
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"latest": None}
    payload = row.payload or {}
    buckets = payload.get("buckets", {})
    return {
        "latest": {
            "id": str(row.id),
            "created_at": row.created_at.isoformat(),
            "generated_at": payload.get("generated_at"),
            "seen": row.seen,
            "bucket_counts": {k: len(v or []) for k, v in buckets.items()},
            "total_entries": sum(len(v or []) for v in buckets.values()),
        }
    }


async def _system_panel(db: AsyncSession, *, settings) -> dict:
    """Postgres version + DB size + disk usage + process uptime."""
    version = (await db.execute(sql_text("SELECT version();"))).scalar_one()

    db_size_pretty, db_size_bytes = (
        await db.execute(
            sql_text(
                "SELECT pg_size_pretty(pg_database_size(current_database())), "
                "pg_database_size(current_database());"
            )
        )
    ).one()

    storage_path = settings.storage_path
    disk = _disk_usage(storage_path)

    # Process uptime — read the lifespan's start-time global.
    from app.lifespan import PROCESS_START_TIME

    if PROCESS_START_TIME is None:
        uptime_seconds = None
        process_started_at = None
    else:
        process_started_at = PROCESS_START_TIME.isoformat()
        uptime_seconds = int((datetime.now(tz=UTC) - PROCESS_START_TIME).total_seconds())

    return {
        "postgres": {
            "version": str(version),
            "db_size_pretty": str(db_size_pretty),
            "db_size_bytes": int(db_size_bytes),
        },
        "storage_path": storage_path,
        "disk_usage": disk,
        "process_started_at": process_started_at,
        "uptime_seconds": uptime_seconds,
        "env": settings.env,
    }


def _disk_usage(path: str) -> dict | None:
    """Bytes total/used/free for the given path. Returns None if the path
    doesn't exist (e.g. tests run outside the container)."""
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": path,
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
        }
    except FileNotFoundError:
        return None
