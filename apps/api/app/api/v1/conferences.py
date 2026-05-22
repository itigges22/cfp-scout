"""/api/v1/conferences — basic read endpoints + SME ranking (plan 18).

Pass-1 surface; plan 20 builds the rich detail page on top. For now:

  * ``GET /conferences``          — paginated list (filter by status)
  * ``GET /conferences/{id}``     — single row
  * ``GET /conferences/{id}/smes`` — ranked SMEs with per-dimension breakdown
                                     + near-misses (plan 18)
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.db.models.entities import Conference
from app.db.session import DbSession
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


class ConferenceListResponse(BaseModel):
    items: list[ConferenceRead]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=ConferenceListResponse)
async def list_conferences(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    status_in: list[str] | None = Query(default=None, alias="status"),
) -> ConferenceListResponse:
    """List conferences. Default excludes quarantined rows so the dashboard
    doesn't show them. Pass ``?status=quarantined`` (multi-OK) to opt in.
    """
    stmt = select(Conference)
    if status_in:
        stmt = stmt.where(Conference.status.in_(status_in))
    else:
        stmt = stmt.where(Conference.status != "quarantined")
    stmt = stmt.order_by(
        Conference.start_date.asc().nullslast(),
        Conference.confidence_score.desc().nullslast(),
    )

    total_q = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(total_q)).scalar_one()
    rows = (
        await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))
    ).scalars().all()

    return ConferenceListResponse(
        items=[_to_read(r) for r in rows],
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
    result = await rank_smes_for_conference(
        db, conference_id, k=k, gate=settings.match_s_gate
    )
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
        "above_gate": [b.to_dict() for b in result.above_gate],
        "near_misses": [b.to_dict() for b in result.near_misses],
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
