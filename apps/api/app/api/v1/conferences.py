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
from app.services.matcher import ALGORITHM_VERSION
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
    is_virtual: bool
    website: str | None = None
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


class ConferenceListResponse(BaseModel):
    items: list[ConferenceListItem]
    total: int
    page: int
    per_page: int


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


@router.get("", response_model=ConferenceListResponse)
async def list_conferences(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    status_in: list[str] | None = Query(default=None, alias="status"),
    sort: Literal["score", "date", "name"] = Query(default="score"),
) -> ConferenceListResponse:
    """List conferences. Default excludes quarantined rows so the dashboard
    doesn't show them. Pass ``?status=quarantined`` (multi-OK) to opt in.

    LEFT JOINs the latest matches row (by algorithm_version) so the list
    can render scores without an N+1 round-trip.
    """
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
    elif sort == "date":
        stmt = stmt.order_by(
            Conference.start_date.asc().nullslast(),
            Match.overall_score.desc().nullslast(),
        )
    else:  # name
        stmt = stmt.order_by(Conference.name.asc())

    # Count the conferences (not the joined rows).
    count_stmt = select(func.count(Conference.id)).where(
        Conference.status.in_(status_in) if status_in else Conference.status != "quarantined"
    )
    total = (await db.execute(count_stmt)).scalar_one()

    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).all()

    items: list[ConferenceListItem] = []
    for conf, match in rows:
        base = _to_read(conf).model_dump()
        item = ConferenceListItem(
            **base,
            overall_score=float(match.overall_score) if match else None,
            messaging_score=float(match.messaging_score) if match else None,
            pillar_score=float(match.pillar_score) if match else None,
            sme_score=float(match.sme_score) if match else None,
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
    """Latest match row for this conference (current algorithm_version)."""
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
        topics=list(row.topics or []),
        cfp_topics_of_interest=list(row.cfp_topics_of_interest or []),
        cfp_close_at=row.cfp_close_at.isoformat() if row.cfp_close_at else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
