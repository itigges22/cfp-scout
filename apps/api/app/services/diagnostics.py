"""Is this deployment actually working? — and the ops key-value store.

WHAT THIS DOES
    Aggregates every health signal the admin page shows: database
    reachability, migration state, the live LLM probe, embedding coverage,
    scheduler and job health, spend against budget, and the last error per
    subsystem.

    ``ops_state`` is the small key-value store behind several of those —
    last-run timestamps, last-seen errors, clearable flags.

HOW IT CONNECTS
    Called by   api/v1/diagnostics.py
    Reads       nearly everything; writes app.ops_state
    Helpers     services/llm.py (the probe), services/settings_store.py

WORTH KNOWING
    ``ops_state`` exists so operational state stops being smuggled into
    app_setting_overrides. A setting is something an operator CHOOSES; a
    last-run timestamp is something the system RECORDS. The override store
    rejects any name not in settings_spec.SPECS precisely to keep that
    line, and this is where the rejected things go.

    The LLM probe is live, not cached — a green light that could be five
    minutes stale is worse than no light.
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
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AudienceProfile,
    Conference,
    ConferenceSeries,
    Decision,
    EmbeddingModel,
    IngestJob,
    LLMCall,
    Match,
    Notification,
    OpsState,
    Participation,
    RawPage,
    Sme,
    Source,
    TalkSubmission,
)
from app.lifespan import PROCESS_START_TIME
from app.scheduler import get_scheduler
from app.services import settings_store
from app.services.llm import normalize_openai_base_url
from app.settings import get_settings

log = structlog.get_logger("scout.diagnostics")


# ==========================================================================
# diagnostics.py
# ==========================================================================


CACHE_TTL_SECONDS = 30.0


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


async def _build(db: AsyncSession) -> dict[str, Any]:
    """Run the panel queries."""
    settings = get_settings()
    now = datetime.now(tz=UTC)

    usage_panel = await _usage_panel(db, now=now)
    llm_panel = await _llm_panel(db, now=now)
    jobs_panel = await _jobs_panel(db, now=now)
    scraper_panel = await _scraper_panel(db)
    data_panel = await _data_panel(db, settings=settings)
    digest_panel = await _digest_panel(db)
    system_panel = await _system_panel(db, settings=settings)

    return {
        "generated_at": now.isoformat(),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "usage": usage_panel,
        "llm": llm_panel,
        "jobs": jobs_panel,
        "scraper": scraper_panel,
        "data": data_panel,
        "digest": digest_panel,
        "system": system_panel,
    }


async def _usage_panel(db: AsyncSession, *, now: datetime) -> dict:
    """Key app-usage metrics: approvals, talks linked, past events, scoring."""
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Conferences by status.
    conf_status_rows = (
        await db.execute(
            select(Conference.status, func.count(Conference.id)).group_by(Conference.status)
        )
    ).all()
    conferences_by_status = {s: int(n) for s, n in conf_status_rows}

    # Conferences that have been scored (have at least one match row).
    conferences_scored = int(
        (
            await db.execute(
                select(func.count(func.distinct(Match.conference_id)))
            )
        ).scalar_one()
    )

    # Decisions — counts by time window.
    decisions_7d = int(
        (
            await db.execute(
                select(func.count(Decision.id)).where(Decision.decided_at >= week_ago)
            )
        ).scalar_one()
    )
    decisions_30d = int(
        (
            await db.execute(
                select(func.count(Decision.id)).where(Decision.decided_at >= month_ago)
            )
        ).scalar_one()
    )
    decisions_all_time = int(
        (await db.execute(select(func.count(Decision.id)))).scalar_one()
    )

    # Decisions by outcome — for each window.
    async def _outcome_breakdown(since: datetime | None) -> dict[str, int]:
        q = select(Decision.decision, func.count(Decision.id)).group_by(Decision.decision)
        if since is not None:
            q = q.where(Decision.decided_at >= since)
        rows = (await db.execute(q)).all()
        return {d: int(n) for d, n in rows}

    decisions_by_outcome_7d = await _outcome_breakdown(week_ago)
    decisions_by_outcome_30d = await _outcome_breakdown(month_ago)
    decisions_by_outcome_all = await _outcome_breakdown(None)

    # Talk submissions (talks linked to conferences).
    talk_submissions_total = int(
        (await db.execute(select(func.count(TalkSubmission.id)))).scalar_one()
    )

    # Conferences somebody actually went to, and how many of those have a
    # retrospective verdict recorded against them.
    conferences_attended = int(
        (
            await db.execute(
                select(func.count(func.distinct(Participation.conference_id)))
            )
        ).scalar_one()
    )
    conferences_attended_scored = int(
        (
            await db.execute(
                select(func.count(func.distinct(Conference.id)))
                .join(Participation, Participation.conference_id == Conference.id)
                .where(Conference.attendance_verdict.is_not(None))
                .where(Conference.attendance_verdict != "unsure")
            )
        ).scalar_one()
    )

    # Active SMEs.
    smes_active = int(
        (
            await db.execute(select(func.count(Sme.id)).where(Sme.is_active.is_(True)))
        ).scalar_one()
    )

    return {
        "conferences_by_status": conferences_by_status,
        "conferences_scored": conferences_scored,
        "decisions": {
            "7d": decisions_7d,
            "30d": decisions_30d,
            "all": decisions_all_time,
        },
        "decisions_by_outcome": {
            "7d": decisions_by_outcome_7d,
            "30d": decisions_by_outcome_30d,
            "all": decisions_by_outcome_all,
        },
        "talk_submissions_total": talk_submissions_total,
        "conferences_attended": conferences_attended,
        "conferences_attended_scored": conferences_attended_scored,
        "smes_active": smes_active,
    }


def _mask_secret(value: str | None) -> str | None:
    """Show only the last 4 chars — enough to tell keys apart, no more."""
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) > 4 else "…"


async def _probe_models_endpoint(base_url: str, api_key: str) -> dict:
    """Authenticated GET {base}/models — a real key + reachability check
    that costs zero tokens. Returns the model ids the backend actually
    serves so we can flag configured-but-missing models."""
    import httpx


    url = normalize_openai_base_url(base_url).rstrip("/") + "/models"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code in (401, 403):
            return {
                "ok": False,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "error": f"authentication failed ({resp.status_code}) — the API key is invalid or revoked",
                "available_models": None,
            }
        if resp.status_code != 200:
            return {
                "ok": False,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "error": f"unexpected status {resp.status_code}: {resp.text[:200]}",
                "available_models": None,
            }
        ids = [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
        return {
            "ok": True,
            "status_code": 200,
            "latency_ms": latency_ms,
            "error": None,
            "available_models": ids[:50],
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "error": f"{type(exc).__name__}: {exc}",
            "available_models": None,
        }


async def _llm_connectivity() -> dict:
    """Live probe of the configured LLM endpoint(s).

    Unlike the call-history panel below, this actually talks to the
    backend — so a rotated-out key or a decommissioned model shows up
    here even when nothing has made an LLM call recently (or dry-run
    has been silently swallowing every call).
    """

    s = get_settings()
    chat_key = s.llm_api_key.get_secret_value() if s.llm_api_key else ""
    probe = await _probe_models_endpoint(s.llm_base_url, chat_key)

    # When a dedicated embedding endpoint/key is configured, check the
    # embedding model against THAT endpoint, not the chat one.
    embed_key_obj = getattr(s, "llm_embedding_api_key", None)
    embed_base = getattr(s, "llm_embedding_base_url", "") or ""
    embed_probe = None
    if embed_key_obj is not None or (embed_base and embed_base != s.llm_base_url):
        embed_probe = await _probe_models_endpoint(
            embed_base or s.llm_base_url,
            embed_key_obj.get_secret_value() if embed_key_obj is not None else chat_key,
        )

    def _available(p: dict | None, model: str) -> bool | None:
        if p is None or not p.get("ok") or p.get("available_models") is None:
            return None
        return model in p["available_models"]

    return {
        "endpoint": probe,
        "embedding_endpoint": embed_probe,
        "chat_model_available": _available(probe, s.llm_chat_model),
        "embedding_model_available": _available(embed_probe or probe, s.llm_embedding_model),
        "config": {
            "base_url": s.llm_base_url,
            "chat_model": s.llm_chat_model,
            "embedding_model": s.llm_embedding_model,
            "dry_run": s.llm_dry_run,
            "api_key_masked": _mask_secret(chat_key),
            "api_key_source": (
                "db_override" if settings_store.has("llm_api_key") else "env"
            ),
            "embedding_key_set": embed_key_obj is not None,
        },
    }


async def _llm_panel(db: AsyncSession, *, now: datetime) -> dict:
    """LLM call activity + a live connectivity probe."""
    datetime(now.year, now.month, 1, tzinfo=UTC)
    day_start = now - timedelta(hours=24)
    week_start = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    async def _call_count(since: datetime | None) -> int:
        q = select(func.count(LLMCall.id))
        if since is not None:
            q = q.where(LLMCall.created_at >= since)
        return int((await db.execute(q)).scalar_one())

    calls_24h = await _call_count(day_start)
    calls_7d = await _call_count(week_start)
    calls_30d = await _call_count(month_ago)
    calls_all = await _call_count(None)

    # Last 24h by purpose — calls only.
    by_purpose_rows = (
        await db.execute(
            select(LLMCall.purpose, func.count(LLMCall.id))
            .where(LLMCall.created_at >= day_start)
            .group_by(LLMCall.purpose)
            .order_by(func.count(LLMCall.id).desc())
        )
    ).all()
    by_purpose = [{"purpose": p, "calls": int(n)} for p, n in by_purpose_rows]

    # Recent errors — filtered past the operator's "clear errors"
    # watermark so stale pre-fix failures don't haunt the panel forever.

    cleared_raw = await get(db, "diagnostics_llm_errors_cleared_at")
    cleared_at: datetime | None = None
    if cleared_raw:
        try:
            cleared_at = datetime.fromisoformat(str(cleared_raw))
        except ValueError:
            pass

    err_q = (
        select(LLMCall.created_at, LLMCall.model, LLMCall.purpose, LLMCall.error)
        .where(LLMCall.error.is_not(None))
        .order_by(LLMCall.created_at.desc())
        .limit(10)
    )
    if cleared_at is not None:
        err_q = err_q.where(LLMCall.created_at > cleared_at)
    err_rows = (await db.execute(err_q)).all()
    recent_errors = [
        {"at": dt.isoformat() if dt else None, "model": m, "purpose": p, "error": (e or "")[:200]}
        for dt, m, p, e in err_rows
    ]

    # Success signal: the panel previously only surfaced errors, so a
    # healthy-but-idle system and a broken one looked identical.
    last_ok = (
        await db.execute(
            select(LLMCall.created_at, LLMCall.model, LLMCall.purpose, LLMCall.latency_ms)
            .where(LLMCall.error.is_(None))
            .order_by(LLMCall.created_at.desc())
            .limit(1)
        )
    ).first()
    ok_24h = int(
        (
            await db.execute(
                select(func.count(LLMCall.id))
                .where(LLMCall.created_at >= day_start)
                .where(LLMCall.error.is_(None))
            )
        ).scalar_one()
    )
    errors_24h = int(
        (
            await db.execute(
                select(func.count(LLMCall.id))
                .where(LLMCall.created_at >= day_start)
                .where(LLMCall.error.is_not(None))
            )
        ).scalar_one()
    )

    return {
        "calls": {"24h": calls_24h, "7d": calls_7d, "30d": calls_30d, "all": calls_all},
        "calls_24h_ok": ok_24h,
        "calls_24h_errors": errors_24h,
        "last_success": (
            {
                "at": last_ok[0].isoformat() if last_ok[0] else None,
                "model": last_ok[1],
                "purpose": last_ok[2],
                "latency_ms": last_ok[3],
            }
            if last_ok
            else None
        ),
        "errors_cleared_at": cleared_raw,
        "by_purpose_24h": by_purpose,
        "recent_errors": recent_errors,
        "connectivity": await _llm_connectivity(),
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

    # Pending series suggestions (computed on demand; we just
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

    # Freshness histogram.


    return {
        "conferences_by_status": conferences_by_status,
        "smes": {
            "total_active": int(smes_total),
            "no_audiences": int(smes_no_audiences),
            "short_bio": int(smes_short_bio),
        },
        "audiences_active": int(audiences_active),
        "series": {
            "active_count": int(series_count),
            "unlinked_conferences": int(unlinked_conferences),
        },
        "embedding_model": embedding_model,
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


# ==========================================================================
# py
# ==========================================================================


async def get(db: AsyncSession, key: str) -> str | None:
    """Current value for ``key``, or None if never set."""
    return (
        await db.execute(select(OpsState.value).where(OpsState.key == key))
    ).scalar_one_or_none()


async def set_value(db: AsyncSession, key: str, value: str) -> None:
    """Write ``key``. Caller commits."""
    await db.execute(
        insert(OpsState)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )
    log.info("set", key=key)
