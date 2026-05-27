"""/api/v1/conferences — basic read endpoints + SME ranking (plan 18).

Pass-1 surface; plan 20 builds the rich detail page on top. For now:

  * ``GET /conferences``          — paginated list (filter by status)
  * ``GET /conferences/{id}``     — single row
  * ``GET /conferences/{id}/smes`` — ranked SMEs with per-dimension breakdown
                                     + near-misses (plan 18)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.db.models.entities import Conference, ConferenceSource, RawPage
from app.db.models.matching import Decision, Match, MatchTeamRecommendation
from app.db.session import DbSession
from app.services._common import model_to_audit_dict, write_audit
from app.services.extraction.dedup import build_slug, find_duplicate, year_for
from app.services.graph import invalidate as invalidate_graph
from app.services.matcher import ALGORITHM_VERSION, run_fit_match
from app.services.matcher.pipeline import (
    ConferenceNotFoundError,
    ConferenceQuarantinedError,
)
from app.services.matcher.sme_ranker import rank_smes_for_conference
from app.settings import get_settings

log = structlog.get_logger("scout.api.conferences")
router = APIRouter(prefix="/api/v1/conferences", tags=["conferences"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class ConferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    name: str
    slug: str
    status: str
    confidence_score: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    location_city: str | None = None
    location_country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_virtual: bool
    website: str | None = None
    cfp_url: str | None = None
    topics: list[str] = []
    cfp_topics_of_interest: list[str] = []
    cfp_close_at: str | None = None
    created_at: datetime
    updated_at: datetime


class ConferenceListItem(ConferenceRead):
    """List-row shape — adds matcher scores from the latest match row."""

    overall_score: float | None = None
    messaging_score: float | None = None
    pillar_score: float | None = None
    sme_score: float | None = None
    # True when a normalized-name match exists in app.past_conferences
    # where attended_sme_ids is non-empty — the operator's team
    # already attended a past edition of this event series.
    previously_attended: bool = False


class ConferenceListResponse(BaseModel):
    items: list[ConferenceListItem]
    total: int
    page: int
    per_page: int


class ConferenceCreate(BaseModel):
    """POST /conferences payload. Slug is server-derived from name+year."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    location_city: str | None = Field(default=None, max_length=120)
    location_country: str | None = Field(
        default=None, min_length=2, max_length=2, description="ISO-3166-1 alpha-2."
    )
    is_virtual: bool = False
    venue: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=2000)
    cfp_url: str | None = Field(default=None, max_length=2000)
    cfp_open_at: date | None = None
    cfp_close_at: date | None = None
    cfp_topics_of_interest: list[str] = Field(default_factory=list, max_length=30)
    topics: list[str] = Field(default_factory=list, max_length=30)
    acceptance_rate_percent: int | None = Field(default=None, ge=0, le=100)
    estimated_cost_usd: int | None = Field(default=None, ge=0, le=100_000)
    actor_label: str = Field(default="manual_entry", max_length=120)


class ConferenceCreateResponse(BaseModel):
    """Return shape for POST /conferences — the new row plus the matcher
    verdict from the auto-run that fires right after the insert commit."""

    conference: ConferenceRead
    match: dict | None = None
    match_error: str | None = None


class DecisionCreate(BaseModel):
    """POST /conferences/{id}/decisions payload."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approved", "rejected", "needs_review"]
    reason: str | None = Field(default=None, max_length=2000)
    decided_by_label: str = Field(default="anonymous", max_length=120)


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    conference_id: UUID
    decision: str
    reason: str | None
    decided_by_label: str
    decided_at: datetime
    created_at: datetime


class StatsCard(BaseModel):
    upcoming_approved: int
    pending_review: int
    cfp_closing_soon: int
    low_coverage_smes: int


class TopConferenceSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    overall_score: float | None
    start_date: str | None


class DashboardStats(BaseModel):
    cards: StatsCard
    top_conferences: list[TopConferenceSummary]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/stats/by-location")
async def stats_by_location(db: DbSession) -> dict:
    """Geocoded conferences for the dashboard map.

    Returns one item per conference with non-null lat/lng. The UI clusters
    by (lat, lng) to draw a single dot per city; clicking it shows the
    list of conferences at that point.

    Excludes virtual events (they have no physical location) and
    quarantined / rejected conferences (clutter, not actionable).
    """
    rows = (
        await db.execute(
            select(
                Conference.id,
                Conference.name,
                Conference.location_city,
                Conference.location_country,
                Conference.latitude,
                Conference.longitude,
                Conference.status,
                Conference.start_date,
            )
            .where(Conference.latitude.is_not(None))
            .where(Conference.longitude.is_not(None))
            .where(Conference.is_virtual.is_(False))
            .where(Conference.status.not_in(["quarantined", "rejected"]))
        )
    ).all()
    return {
        "items": [
            {
                "id": str(r.id),
                "name": r.name,
                "city": r.location_city,
                "country": r.location_country,
                "lat": float(r.latitude),
                "lng": float(r.longitude),
                "status": r.status,
                "start_date": r.start_date.isoformat() if r.start_date else None,
            }
            for r in rows
        ]
    }


@router.get("/stats/dashboard", response_model=DashboardStats)
async def dashboard_stats(db: DbSession) -> DashboardStats:
    """Aggregates the four headline numbers + top-N conferences for the
    dashboard. Bounded; single round-trip per card to keep this snappy."""
    today = date.today()
    next_90 = today + timedelta(days=90)
    next_30 = today + timedelta(days=30)

    upcoming_approved = (
        await db.execute(
            select(func.count(Conference.id))
            .where(Conference.status == "approved")
            .where(Conference.start_date.is_not(None))
            .where(Conference.start_date.between(today, next_90))
        )
    ).scalar_one()

    pending_review = (
        await db.execute(
            select(func.count(Conference.id)).where(
                Conference.status.in_(
                    [
                        "needs_review",
                        "needs_review_pillar",
                        "needs_sme_review",
                    ]
                )
            )
        )
    ).scalar_one()

    cfp_closing_soon = (
        await db.execute(
            select(func.count(Conference.id))
            .where(Conference.cfp_close_at.is_not(None))
            .where(Conference.cfp_close_at.between(today, next_30))
            .where(Conference.status != "quarantined")
        )
    ).scalar_one()

    # "Low coverage" SME = active SME with empty primary_topics OR empty
    # audience_focus. Cheap proxy until plan 26 builds a richer signal.
    from app.db.models.entities import Sme  # local import keeps top tidy

    low_coverage_smes = (
        await db.execute(
            select(func.count(Sme.id))
            .where(Sme.is_active.is_(True))
            .where(
                (func.array_length(Sme.primary_topics, 1).is_(None))
                | (func.array_length(Sme.audience_focus, 1).is_(None))
            )
        )
    ).scalar_one()

    # Top conferences by overall_score, capped at 5 — the dashboard list.
    top_rows = (
        await db.execute(
            select(Conference, Match)
            .outerjoin(
                Match,
                (Match.conference_id == Conference.id)
                & (Match.algorithm_version == ALGORITHM_VERSION),
            )
            .where(Conference.status != "quarantined")
            .order_by(Match.overall_score.desc().nullslast())
            .limit(5)
        )
    ).all()

    top = [
        TopConferenceSummary(
            id=c.id,
            name=c.name,
            slug=c.slug,
            status=c.status,
            overall_score=float(m.overall_score) if m else None,
            start_date=c.start_date.isoformat() if c.start_date else None,
        )
        for c, m in top_rows
    ]

    return DashboardStats(
        cards=StatsCard(
            upcoming_approved=int(upcoming_approved),
            pending_review=int(pending_review),
            cfp_closing_soon=int(cfp_closing_soon),
            low_coverage_smes=int(low_coverage_smes),
        ),
        top_conferences=top,
    )


@router.post("", response_model=ConferenceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_conference(
    db: DbSession,
    payload: ConferenceCreate,
) -> ConferenceCreateResponse:
    """Manually add a conference + immediately run the matcher.

    Slug is derived from ``name + year`` server-side (mirrors the extraction
    pipeline's dedup contract). 409 if a conference with the same slug
    already exists. `confidence_score=1.0` for manual entries since a human
    just vouched for them; the matcher will set ``status`` based on its
    gates.

    The matcher runs synchronously in the same request so the caller gets
    the verdict back without polling. If the matcher fails (e.g. LLM
    outage), the conference is still created and ``match_error`` is
    populated; the caller can re-run the matcher later via
    ``POST /admin/matcher/run-now/{id}``.
    """
    slug = build_slug(payload.name, year_for(payload.start_date))
    existing = await find_duplicate(db, slug=slug)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Conference with slug '{slug}' already exists "
                f"(id={existing.id}). Open it instead of recreating."
            ),
        )

    conf = Conference(
        name=payload.name,
        slug=slug,
        start_date=payload.start_date,
        end_date=payload.end_date,
        location_city=payload.location_city,
        location_country=payload.location_country,
        is_virtual=payload.is_virtual,
        venue=payload.venue,
        website=payload.website,
        cfp_url=payload.cfp_url,
        cfp_open_at=payload.cfp_open_at,
        cfp_close_at=payload.cfp_close_at,
        cfp_topics_of_interest=list(payload.cfp_topics_of_interest),
        cfp_deadlines=[],
        topics=list(payload.topics),
        acceptance_rate_percent=payload.acceptance_rate_percent,
        estimated_cost_usd=payload.estimated_cost_usd,
        confidence_score=1.0,
        status="discovered",
    )
    db.add(conf)
    await db.flush()

    await write_audit(
        db,
        action="conference.manual_create",
        target_type="conference",
        target_id=conf.id,
        before=None,
        after=model_to_audit_dict(conf),
        actor_label=payload.actor_label,
    )
    await db.commit()
    invalidate_graph()

    # Embed the conference's structural blob synchronously so the matcher's
    # Stage A has a chunk to compare messaging documents against. Without
    # this, manually-created conferences always score 0 on messaging /
    # pillar because the embed-on-extract path that the scraper relies
    # on never runs for them. Mirrors the same code in
    # services/extraction/pipeline.py.
    try:
        from app.services.embeddings import embed_owner
        from app.services.extraction.pipeline import _conference_embed_text

        blob = _conference_embed_text(conf)
        if blob:
            await embed_owner(
                db,
                owner_type="conference",
                owner_id=conf.id,
                text=blob,
                purpose="embed:conference",
            )
            await db.commit()
    except Exception as exc:
        log.warning(
            "conference.manual_create.embed_failed",
            conference_id=str(conf.id),
            error=str(exc),
        )

    log.info(
        "conference.manual_create",
        conference_id=str(conf.id),
        slug=conf.slug,
        actor_label=payload.actor_label,
    )

    # Auto-run the matcher; best-effort — surface failure without rolling
    # back the conference create.
    match_dict: dict | None = None
    match_error: str | None = None
    try:
        result = await run_fit_match(db, conf.id)
        await db.commit()
        match_dict = result.to_stats()
    except ConferenceQuarantinedError as exc:
        match_error = f"matcher skipped: {exc}"
    except ConferenceNotFoundError as exc:  # pragma: no cover — we just inserted it
        match_error = f"conference vanished mid-request: {exc}"
    except Exception as exc:
        log.warning(
            "conference.manual_create.matcher_failed",
            conference_id=str(conf.id),
            error=str(exc),
        )
        match_error = f"matcher failed: {exc}"

    # Refresh so the response reflects any status update the matcher made.
    await db.refresh(conf)
    return ConferenceCreateResponse(
        conference=_to_read(conf),
        match=match_dict,
        match_error=match_error,
    )


@router.get("", response_model=ConferenceListResponse)
async def list_conferences(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    status_in: list[str] | None = Query(default=None, alias="status"),
    sort: Literal["score", "messaging", "pillar", "sme", "date", "name"] = Query(
        default="score",
    ),
    attendance_filter: Literal["all", "new", "returning"] = Query(
        default="all",
        description=(
            "Filter by past-attendance status: 'all' (default), 'new' "
            "(conferences whose normalized name doesn't match any "
            "past_conferences row the operator attended), 'returning' "
            "(conferences whose normalized name DOES match a past-attended "
            "edition)."
        ),
    ),
) -> ConferenceListResponse:
    """List conferences. Default excludes quarantined rows so the dashboard
    doesn't show them. Pass ``?status=quarantined`` (multi-OK) to opt in.

    LEFT JOINs the latest matches row (by algorithm_version) so the list
    can render scores without an N+1 round-trip.

    Tags each item with ``previously_attended`` based on a normalized-name
    match against ``app.past_conferences`` (where attended_sme_ids is
    non-empty). The ``attendance_filter`` query parameter narrows the
    result set by that flag.
    """
    from app.services.past_attendance import (
        is_previously_attended,
        load_attended_names,
    )

    attended_names = await load_attended_names(db)

    stmt = select(Conference, Match).outerjoin(
        Match,
        (Match.conference_id == Conference.id) & (Match.algorithm_version == ALGORITHM_VERSION),
    )
    if status_in:
        stmt = stmt.where(Conference.status.in_(status_in))
    else:
        stmt = stmt.where(Conference.status != "quarantined")

    if sort == "score":
        stmt = stmt.order_by(
            Match.overall_score.desc().nullslast(),
            Conference.start_date.asc().nullslast(),
        )
    elif sort == "messaging":
        stmt = stmt.order_by(
            Match.messaging_score.desc().nullslast(),
            Conference.start_date.asc().nullslast(),
        )
    elif sort == "pillar":
        stmt = stmt.order_by(
            Match.pillar_score.desc().nullslast(),
            Conference.start_date.asc().nullslast(),
        )
    elif sort == "sme":
        stmt = stmt.order_by(
            Match.sme_score.desc().nullslast(),
            Conference.start_date.asc().nullslast(),
        )
    elif sort == "date":
        stmt = stmt.order_by(
            Conference.start_date.asc().nullslast(),
            Match.overall_score.desc().nullslast(),
        )
    else:  # name
        stmt = stmt.order_by(Conference.name.asc())

    # Past-attendance filtering happens in Python because the
    # comparison key is a normalized name (year/edition stripped),
    # not a column we can directly WHERE on. The candidate set is
    # already small after status filter so over-fetch + filter
    # in-app is fine. We still cap total to keep pagination math
    # honest.
    all_rows = (await db.execute(stmt)).all()
    if attendance_filter != "all":
        attended = attendance_filter == "returning"
        all_rows = [
            (c, m) for c, m in all_rows
            if is_previously_attended(c.name, attended_names) == attended
        ]
    total = len(all_rows)
    rows = all_rows[(page - 1) * per_page : page * per_page]

    items: list[ConferenceListItem] = []
    for conf, match in rows:
        base = _to_read(conf).model_dump()
        item = ConferenceListItem(
            **base,
            overall_score=float(match.overall_score) if match else None,
            messaging_score=float(match.messaging_score) if match else None,
            pillar_score=float(match.pillar_score) if match else None,
            sme_score=float(match.sme_score) if match else None,
            previously_attended=is_previously_attended(conf.name, attended_names),
        )
        items.append(item)

    return ConferenceListResponse(
        items=items,
        total=int(total),
        page=page,
        per_page=per_page,
    )


@router.get("/{conference_id}", response_model=ConferenceRead)
async def get_conference(db: DbSession, conference_id: UUID) -> ConferenceRead:
    row = await db.get(Conference, conference_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    return _to_read(row)


@router.delete("/{conference_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conference(
    db: DbSession,
    conference_id: UUID,
    actor_label: str = Query(default="user_delete", max_length=120),
) -> None:
    """Hard-delete a conference + all rows that reference it.

    The model FKs are declared ``ondelete='CASCADE'`` (matches, decisions,
    conference_sources, conference_topics, conference_audiences,
    conference_pillars, conference_smes, conference_team_recommendations,
    raw_pages-via-conference_sources). The single DELETE cascades; we
    invalidate the graph cache + log the deletion afterwards so admins
    have an audit trail.
    """
    row = await db.get(Conference, conference_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    snapshot = model_to_audit_dict(row)
    await db.delete(row)
    await write_audit(
        db,
        action="conference.delete",
        target_type="conference",
        target_id=conference_id,
        before=snapshot,
        after=None,
        actor_label=actor_label,
    )
    await db.commit()
    invalidate_graph()
    log.info(
        "conference.deleted",
        conference_id=str(conference_id),
        slug=snapshot.get("slug"),
        actor_label=actor_label,
    )


@router.get("/{conference_id}/smes")
async def conference_smes(
    db: DbSession,
    conference_id: UUID,
    k: int = Query(default=5, ge=1, le=20),
) -> dict:
    """Ranked SMEs for this conference with per-dimension breakdown.

    Response:

        {
          "conference_id": "...",
          "gate": 0.5,
          "weights": {...},                  # SME composite weights
          "above_gate": [{...breakdown}],
          "near_misses": [{...breakdown}]
        }

    Each breakdown:
      ``{sme_id, full_name, team, is_external, location_country, location_city,
         dimensions: {topic_overlap, audience_overlap, bio_similarity,
                      location, past_attendance},
         composite, above_gate}``
    """
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    settings = get_settings()
    result = await rank_smes_for_conference(db, conference_id, k=k, gate=settings.match_s_gate)

    # Surface any persisted SME-fit narratives (plan 19) so the UI can show
    # the per-SME paragraph next to the mechanical breakdown without an
    # extra round-trip.
    match = (
        await db.execute(
            select(Match)
            .where(Match.conference_id == conference_id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
        )
    ).scalar_one_or_none()
    narratives_by_sme: dict = dict(match.sme_fit_narratives or {}) if match else {}

    def _attach_narrative(b) -> dict:
        d = b.to_dict()
        d["narrative"] = narratives_by_sme.get(b.sme_id)
        return d

    return {
        "conference_id": str(conference_id),
        "gate": settings.match_s_gate,
        "weights": {
            "topic": settings.sme_w_topic,
            "audience": settings.sme_w_audience,
            "bio": settings.sme_w_bio,
            "location": settings.sme_w_location,
            "past": settings.sme_w_past,
        },
        "narrative_top_k": settings.sme_narrative_top_k,
        "above_gate": [_attach_narrative(b) for b in result.above_gate],
        "near_misses": [_attach_narrative(b) for b in result.near_misses],
    }


@router.get("/{conference_id}/match")
async def conference_match(db: DbSession, conference_id: UUID) -> dict:
    """Latest match row for this conference (current algorithm_version).

    Auto-runs the matcher inline if no match exists yet for this version.
    The detail page should be self-sufficient — the user shouldn't have
    to know about a separate "run matcher" step. UI shows a skeleton
    while this endpoint runs, so paying the matcher cost here is fine.
    """
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    match = (
        await db.execute(
            select(Match)
            .where(Match.conference_id == conference_id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
        )
    ).scalar_one_or_none()
    if match is None:
        try:
            from app.services.matcher import run_fit_match

            log.info("conference.match.auto_run", conference_id=str(conference_id))
            await run_fit_match(db, conference_id)
            await db.commit()
            match = (
                await db.execute(
                    select(Match)
                    .where(Match.conference_id == conference_id)
                    .where(Match.algorithm_version == ALGORITHM_VERSION)
                )
            ).scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001 — surface to UI, don't 500
            log.warning(
                "conference.match.auto_run_failed",
                conference_id=str(conference_id),
                error=str(exc)[:200],
            )
    if match is None:
        return {
            "conference_id": str(conference_id),
            "algorithm_version": ALGORITHM_VERSION,
            "match": None,
        }
    return {
        "conference_id": str(conference_id),
        "algorithm_version": ALGORITHM_VERSION,
        "match": {
            "id": str(match.id),
            "messaging_score": round(float(match.messaging_score), 4),
            "pillar_score": round(float(match.pillar_score), 4),
            "sme_score": round(float(match.sme_score), 4),
            "overall_score": round(float(match.overall_score), 4),
            "recommended_sme_ids": [str(s) for s in match.recommended_sme_ids],
            "rationale_text": match.rationale_text,
            "computed_at": match.computed_at.isoformat() if match.computed_at else None,
        },
    }


@router.get("/{conference_id}/sources")
async def conference_sources(db: DbSession, conference_id: UUID) -> dict:
    """Raw-page contributors to this conference (plan 14 → plan 15 chain)."""
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )

    rows = (
        (
            await db.execute(
                select(RawPage)
                .join(ConferenceSource, ConferenceSource.raw_page_id == RawPage.id)
                .where(ConferenceSource.conference_id == conference_id)
                .order_by(RawPage.fetched_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "conference_id": str(conference_id),
        "sources": [
            {
                "raw_page_id": str(r.id),
                "url": r.url,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                "http_status": r.http_status,
                "parse_status": r.parse_status,
                "hash_prefix": (r.hash or "")[:12],
            }
            for r in rows
        ],
    }


@router.post(
    "/{conference_id}/decisions",
    response_model=DecisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_decision(
    db: DbSession,
    conference_id: UUID,
    payload: DecisionCreate,
) -> DecisionRead:
    """Record an approve / reject / needs_review action on this conference.

    Also bumps ``conferences.status`` to the decision value so the dashboard
    filter reflects the human-in-the-loop verdict. Audit-logged.
    """
    conference = await db.get(Conference, conference_id)
    if conference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )

    before = model_to_audit_dict(conference)

    decision = Decision(
        conference_id=conference.id,
        decision=payload.decision,
        reason=payload.reason,
        decided_by_label=payload.decided_by_label or "anonymous",
    )
    db.add(decision)
    conference.status = payload.decision
    await db.flush()
    await db.refresh(conference)
    await db.refresh(decision)

    await write_audit(
        db,
        action=f"decision.{payload.decision}",
        target_type="conference",
        target_id=conference.id,
        before=before,
        after=model_to_audit_dict(conference),
        actor_label=payload.decided_by_label or "anonymous",
    )
    await db.commit()
    log.info(
        "conference.decision",
        conference_id=str(conference.id),
        decision=payload.decision,
        actor=payload.decided_by_label,
    )
    return DecisionRead.model_validate(decision)


@router.get("/{conference_id}/decisions")
async def list_decisions(db: DbSession, conference_id: UUID) -> dict:
    """Decision history for this conference (newest first)."""
    rows = (
        (
            await db.execute(
                select(Decision)
                .where(Decision.conference_id == conference_id)
                .order_by(Decision.decided_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "conference_id": str(conference_id),
        "decisions": [DecisionRead.model_validate(r).model_dump(mode="json") for r in rows],
    }


@router.get("/{conference_id}/team-recommendations")
async def team_recommendations(db: DbSession, conference_id: UUID) -> dict:
    """Plan-32 team picks: size 1 / 2 / 3 with composite + coverage +
    redundancy + rationale. Returns ``{by_size: {1: {...}, ...}}``."""
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    match = (
        await db.execute(
            select(Match)
            .where(Match.conference_id == conference_id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
        )
    ).scalar_one_or_none()
    if match is None:
        return {"conference_id": str(conference_id), "by_size": {}}

    rows = (
        (
            await db.execute(
                select(MatchTeamRecommendation)
                .where(MatchTeamRecommendation.match_id == match.id)
                .order_by(MatchTeamRecommendation.team_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "conference_id": str(conference_id),
        "algorithm_version": ALGORITHM_VERSION,
        "by_size": {
            str(r.team_size): {
                "team_size": r.team_size,
                "sme_ids": [str(s) for s in r.sme_ids],
                "team_score": round(float(r.team_score), 4),
                "coverage_breadth": round(float(r.coverage_breadth), 4),
                "redundancy": round(float(r.redundancy), 4),
                "rationale_text": r.rationale_text,
                "computed_at": r.computed_at.isoformat() if r.computed_at else None,
            }
            for r in rows
        },
    }


def _to_read(row: Conference) -> ConferenceRead:
    return ConferenceRead(
        id=row.id,
        name=row.name,
        slug=row.slug,
        status=row.status,
        confidence_score=row.confidence_score,
        start_date=row.start_date.isoformat() if row.start_date else None,
        end_date=row.end_date.isoformat() if row.end_date else None,
        location_city=row.location_city,
        location_country=row.location_country,
        is_virtual=row.is_virtual,
        website=row.website,
        cfp_url=row.cfp_url,
        topics=list(row.topics or []),
        cfp_topics_of_interest=list(row.cfp_topics_of_interest or []),
        cfp_close_at=row.cfp_close_at.isoformat() if row.cfp_close_at else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
