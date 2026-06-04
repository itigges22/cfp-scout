"""Conference-brief assembler (plan 33 pass 1).

Single-shot denormalized payload covering all nine brief sections:

  1. Header (name, dates, location, website)
  2. At a glance (overall + per-stage scores, series stats, acceptance, cost)
  3. Why we're going (rationale + matched pillar + top topics)
  4. Recommended attendee(s) (team_size 1/2/3)
  5. CFP info (deadlines + topics of interest)
  6. Past team engagement
  7. Talking points (top messaging docs)
  8. Logistics placeholder (rendered client-side)
  9. Footer

Cost: at most one embedding call per ``(conference, team_size)`` cache miss
for the talking-points section. Cached 5 minutes per key.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    Conference,
    ConferenceSeries,
    ConferenceSource,
    MessagingDocument,
    PastConference,
    Sme,
    StrategicPillar,
    Topic,
)
from app.db.models.junctions import ConferencePillar, ConferenceTopic
from app.db.models.matching import Decision, Match, MatchTeamRecommendation
from app.services.embeddings import similar_chunks
from app.services.matcher import ALGORITHM_VERSION
from app.settings import get_settings

log = structlog.get_logger("scout.brief")

CACHE_TTL_SECONDS = 300.0  # 5 minutes per plan 33 spec
_MAX_TOPICS = 10
_MAX_PAST_EDITIONS = 5
_MAX_TALKING_DOCS = 3
_MAX_TALKING_POINTS_PER_DOC = 2


class BriefNotFoundError(LookupError):
    """Conference does not exist."""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _Entry:
    payload: dict[str, Any]
    built_at: float


_cache: dict[tuple[str, int], _Entry] = {}
_lock = asyncio.Lock()


def invalidate_cache(conference_id: UUID | str | None = None) -> None:
    """Drop cached briefs. If ``conference_id`` is given, drops only that
    conference's entries (all team_size variants); otherwise clears everything."""
    if conference_id is None:
        _cache.clear()
        return
    cid = str(conference_id)
    for key in list(_cache):
        if key[0] == cid:
            _cache.pop(key, None)


async def build_brief(
    db: AsyncSession,
    conference_id: UUID,
    *,
    team_size: int = 1,
    force: bool = False,
) -> dict[str, Any]:
    """Build (and cache) the brief payload for ``conference_id``.

    Raises BriefNotFoundError if the conference doesn't exist.

    ``team_size`` selects which team rec to surface in section 4
    (1, 2, or 3). Falls back to the top individual SME if no team rec
    of that size has been computed yet.
    """
    if team_size not in (1, 2, 3):
        team_size = 1

    key = (str(conference_id), team_size)
    now = time.monotonic()
    cached = _cache.get(key)
    if not force and cached is not None and (now - cached.built_at) < CACHE_TTL_SECONDS:
        return cached.payload

    async with _lock:
        cached = _cache.get(key)
        if (
            not force
            and cached is not None
            and (time.monotonic() - cached.built_at) < CACHE_TTL_SECONDS
        ):
            return cached.payload

        payload = await _build(db, conference_id, team_size=team_size)
        _cache[key] = _Entry(payload=payload, built_at=time.monotonic())
        return payload


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
async def _build(
    db: AsyncSession,
    conference_id: UUID,
    *,
    team_size: int,
) -> dict[str, Any]:
    conference = await db.get(Conference, conference_id)
    if conference is None:
        raise BriefNotFoundError(f"No conference {conference_id}")

    match = (
        await db.execute(
            select(Match)
            .where(Match.conference_id == conference.id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
        )
    ).scalar_one_or_none()

    # Auto-run the matcher inline if no match exists yet for this algorithm
    # version. The brief endpoint should be self-sufficient — the user
    # shouldn't have to know about a separate "run matcher" step. The UI
    # already shows a loading spinner while this endpoint runs, so paying
    # the matcher cost here gives the user a single "open brief →
    # populated brief" interaction instead of an empty brief + manual
    # admin command.
    if match is None:
        try:
            from app.services.matcher import run_fit_match

            log.info("brief.auto_match", conference_id=str(conference.id))
            await run_fit_match(db, conference.id)
            await db.commit()
            match = (
                await db.execute(
                    select(Match)
                    .where(Match.conference_id == conference.id)
                    .where(Match.algorithm_version == ALGORITHM_VERSION)
                )
            ).scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001 — surface to brief, don't 500
            log.warning(
                "brief.auto_match_failed",
                conference_id=str(conference.id),
                error=str(exc)[:200],
            )

    series = None
    if conference.series_id is not None:
        series = await db.get(ConferenceSeries, conference.series_id)

    past = await _past_editions(db, conference)
    pillar = await _matched_pillar(db, conference.id)
    topics = await _top_topics(db, conference.id)
    attendees = await _attendees(db, match, team_size)
    decision = await _latest_decision(db, conference.id)
    talking_docs = await _talking_points(db, conference)
    sources_count = await _sources_count(db, conference.id)

    settings = get_settings()
    now = datetime.now(tz=UTC)

    return {
        "conference_id": str(conference.id),
        "generated_at": now.isoformat(timespec="seconds"),
        "algorithm_version": ALGORITHM_VERSION,
        "scout_version": settings.scout_version if hasattr(settings, "scout_version") else "0.1.0",
        "team_size": team_size,
        # --- 1. Header -------------------------------------------------
        "header": {
            "name": conference.name,
            "slug": conference.slug,
            "start_date": _iso_date(conference.start_date),
            "end_date": _iso_date(conference.end_date),
            "location_city": conference.location_city,
            "location_country": conference.location_country,
            "is_virtual": conference.is_virtual,
            "venue": conference.venue,
            "website": conference.website,
        },
        # --- 2. At a glance --------------------------------------------
        "at_a_glance": {
            "overall_score": _round(match.overall_score) if match else None,
            "messaging_score": _round(match.messaging_score) if match else None,
            "pillar_score": _round(match.pillar_score) if match else None,
            "sme_score": _round(match.sme_score) if match else None,
            "overall_bucket": _bucket(match.overall_score) if match else None,
            "status": conference.status,
            "acceptance_rate_percent": conference.acceptance_rate_percent,
            "estimated_cost_usd": conference.estimated_cost_usd,
            "series": _series_summary(series, past) if series else None,
            "freshness_score": _round(conference.freshness_score),
        },
        # --- 3. Why we're going ---------------------------------------
        "why": {
            "rationale_text": match.rationale_text if match else "",
            "matched_pillar": pillar,
            "top_topics": topics[:3],
        },
        # --- 4. Recommended attendee(s) -------------------------------
        "attendees": attendees,
        # --- 5. CFP info ----------------------------------------------
        "cfp": _cfp_section(conference),
        # --- 6. Past engagement ---------------------------------------
        "past_engagement": past,
        # --- 7. Talking points ----------------------------------------
        "talking_points": talking_docs,
        # --- 8. Logistics placeholder ---------------------------------
        # Stored client-side in localStorage; backend just confirms the slot
        # exists so the frontend can render a blank editable area for
        # conferences that don't yet have logistics filled in.
        "logistics_placeholder": {
            "storage_key": f"scout.brief.logistics.{conference.id}",
            "fields": ["travel", "lodging", "swag_booth", "sponsorship_status"],
        },
        # --- 9. Footer -------------------------------------------------
        "footer": {
            "detail_url_path": f"/conferences/{conference.id}",
            "decision": _decision_summary(decision),
            "sources_count": sources_count,
        },
    }


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------
async def _past_editions(db: AsyncSession, conference: Conference) -> list[dict]:
    """Past editions of the same series, plus a 'team attended X of past N'
    rollup that the at_a_glance reuses."""
    if conference.series_id is None:
        return []
    rows = (
        (
            await db.execute(
                select(PastConference)
                .where(PastConference.series_id == conference.series_id)
                .order_by(PastConference.year.desc())
                .limit(_MAX_PAST_EDITIONS)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    sme_ids = {sid for r in rows for sid in r.attended_sme_ids}
    name_by_id: dict[UUID, str] = {}
    if sme_ids:
        sme_rows = (
            await db.execute(select(Sme.id, Sme.full_name).where(Sme.id.in_(list(sme_ids))))
        ).all()
        name_by_id = {sid: name for sid, name in sme_rows}
    return [
        {
            "name": r.name,
            "year": r.year,
            "role": r.role,
            "session_type": r.session_type,
            "notes": r.notes,
            "attendees": [
                {"sme_id": str(sid), "full_name": name_by_id.get(sid, "Unknown SME")}
                for sid in r.attended_sme_ids
            ],
        }
        for r in rows
    ]


async def _matched_pillar(db: AsyncSession, conference_id: UUID) -> dict | None:
    row = (
        await db.execute(
            select(StrategicPillar.name, StrategicPillar.description, ConferencePillar.score)
            .join(StrategicPillar, StrategicPillar.id == ConferencePillar.pillar_id)
            .where(ConferencePillar.conference_id == conference_id)
            .order_by(ConferencePillar.score.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return {"name": row[0], "description": row[1], "score": _round(row[2])}


async def _top_topics(db: AsyncSession, conference_id: UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(Topic.name, Topic.slug, ConferenceTopic.weight)
            .join(Topic, Topic.id == ConferenceTopic.topic_id)
            .where(ConferenceTopic.conference_id == conference_id)
            .where(Topic.is_active)
            .order_by(ConferenceTopic.weight.desc())
            .limit(_MAX_TOPICS)
        )
    ).all()
    return [{"name": n, "slug": s, "weight": _round(w)} for (n, s, w) in rows]


async def _attendees(
    db: AsyncSession,
    match: Match | None,
    team_size: int,
) -> dict:
    """Returns the picked SMEs for ``team_size``. Falls back to top-1
    individual when no team rec exists."""
    if match is None:
        return {"team_size": team_size, "members": [], "rationale_text": "", "source": "none"}

    team = (
        await db.execute(
            select(MatchTeamRecommendation)
            .where(MatchTeamRecommendation.match_id == match.id)
            .where(MatchTeamRecommendation.team_size == team_size)
        )
    ).scalar_one_or_none()

    sme_ids: list[UUID]
    source: str
    rationale: str
    if team is not None:
        sme_ids = list(team.sme_ids)
        rationale = team.rationale_text
        source = "team_rec"
    else:
        sme_ids = list(match.recommended_sme_ids[:team_size])
        rationale = ""
        source = "individual_fallback"

    if not sme_ids:
        return {
            "team_size": team_size,
            "members": [],
            "rationale_text": rationale,
            "source": "empty",
        }

    sme_rows = (await db.execute(select(Sme).where(Sme.id.in_(sme_ids)))).scalars().all()
    sme_by_id = {s.id: s for s in sme_rows}

    narratives = match.sme_fit_narratives or {}
    members: list[dict] = []
    for sid in sme_ids:
        s = sme_by_id.get(sid)
        if s is None:
            continue
        members.append(
            {
                "sme_id": str(s.id),
                "full_name": s.full_name,
                "team": s.team,
                "location_city": s.location_city,
                "location_country": s.location_country,
                "bio": s.bio,
                "narrative": narratives.get(str(s.id)) or narratives.get(s.id) or "",
            }
        )

    return {
        "team_size": team_size,
        "members": members,
        "rationale_text": rationale,
        "source": source,
    }


def _cfp_section(conference: Conference) -> dict:
    deadlines = list(conference.cfp_deadlines or [])
    today = date.today()
    enriched: list[dict] = []
    next_idx: int | None = None
    next_days: int | None = None
    for i, d in enumerate(deadlines):
        date_str = d.get("date") if isinstance(d, dict) else None
        days_remaining: int | None = None
        if date_str:
            try:
                target = date.fromisoformat(date_str)
                days_remaining = (target - today).days
                if days_remaining >= 0 and (next_days is None or days_remaining < next_days):
                    next_days = days_remaining
                    next_idx = i
            except ValueError:
                pass
        enriched.append(
            {
                "kind": d.get("kind") if isinstance(d, dict) else None,
                "date": date_str,
                "description": d.get("description") if isinstance(d, dict) else None,
                "days_remaining": days_remaining,
                "is_next": False,
            }
        )
    if next_idx is not None:
        enriched[next_idx]["is_next"] = True
    return {
        "deadlines": enriched,
        "topics_of_interest": list(conference.cfp_topics_of_interest or [])[:_MAX_TOPICS],
        "open_at": _iso_date(conference.cfp_open_at),
        "close_at": _iso_date(conference.cfp_close_at),
    }


async def _talking_points(
    db: AsyncSession,
    conference: Conference,
) -> list[dict]:
    """Top messaging documents matched against this conference's text.

    One embedding call (the query is the conference name + topics + CFP
    topics of interest). Cached per (conf, team_size) by the outer
    ``build_brief``.
    """
    query_parts: list[str] = [conference.name]
    if conference.topics:
        query_parts.append(" ".join(conference.topics))
    if conference.cfp_topics_of_interest:
        query_parts.append(" ".join(conference.cfp_topics_of_interest))
    query = " ".join(p for p in query_parts if p).strip()
    if not query:
        return []

    try:
        chunks = await similar_chunks(
            db,
            query=query,
            owner_types=["messaging"],
            k=12,
            purpose="brief_talking_points",
            bump_last_used=False,
        )
    except Exception as exc:
        log.warning("brief.talking_points.embed_failed", error=str(exc))
        return []

    seen: dict[UUID, float] = {}
    for c in chunks:
        sim = getattr(c, "__cosine_similarity__", 0.0) or 0.0
        prev = seen.get(c.owner_id)
        if prev is None or sim > prev:
            seen[c.owner_id] = sim
    if not seen:
        return []

    top_ids = sorted(seen, key=lambda i: seen[i], reverse=True)[:_MAX_TALKING_DOCS]
    docs = (
        (await db.execute(select(MessagingDocument).where(MessagingDocument.id.in_(top_ids))))
        .scalars()
        .all()
    )
    by_id = {d.id: d for d in docs}

    out: list[dict] = []
    for did in top_ids:
        d = by_id.get(did)
        if d is None:
            continue
        out.append(
            {
                "document_id": str(d.id),
                "title": d.title,
                "elevator_pitch": d.elevator_pitch,
                "talking_points": (d.talking_points or [])[:_MAX_TALKING_POINTS_PER_DOC],
                "key_themes": (d.key_themes or [])[:_MAX_TALKING_POINTS_PER_DOC],
                "similarity": round(seen[did], 4),
            }
        )
    return out


async def _latest_decision(db: AsyncSession, conference_id: UUID) -> Decision | None:
    return (
        await db.execute(
            select(Decision)
            .where(Decision.conference_id == conference_id)
            .order_by(Decision.decided_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _sources_count(db: AsyncSession, conference_id: UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count(ConferenceSource.raw_page_id)).where(
                    ConferenceSource.conference_id == conference_id
                )
            )
        ).scalar_one()
        or 0
    )


# ---------------------------------------------------------------------------
# Small formatters
# ---------------------------------------------------------------------------
def _series_summary(series: ConferenceSeries, past: list[dict]) -> dict:
    attended_recent = sum(1 for p in past if p["attendees"])
    return {
        "id": str(series.id),
        "canonical_name": series.canonical_name,
        "typical_month": series.typical_month,
        "past_editions_count": len(past),
        "team_attended_recent": attended_recent,
    }


def _decision_summary(d: Decision | None) -> dict | None:
    if d is None:
        return None
    return {
        "decision": d.decision,
        "decided_by_label": d.decided_by_label,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "reason": d.reason,
    }


def _bucket(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 0.75:
        return "strong"
    if score >= 0.55:
        return "good"
    if score >= 0.40:
        return "marginal"
    return "weak"


def _round(x: float | None) -> float | None:
    if x is None:
        return None
    return round(float(x), 4)


def _iso_date(d: date | None) -> str | None:
    return d.isoformat() if d else None
