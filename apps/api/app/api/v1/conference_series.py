"""/api/v1/conference-series — series CRUD + detector + assignment (plan 23).

Endpoints:
  * ``GET    /conference-series``               — list (active by default)
  * ``GET    /conference-series/{id}``          — fetch + member conferences
  * ``POST   /conference-series``               — create
  * ``PATCH  /conference-series/{id}``          — rename / edit aliases / etc
  * ``DELETE /conference-series/{id}``          — deactivate (soft delete)
  * ``GET    /conference-series/suggestions``   — detector run
  * ``POST   /conference-series/{id}/assign``   — link a conference
  * ``POST   /conference-series/{id}/unassign`` — unlink a conference

No automatic bulk-link endpoint by design — the plan calls for human-in-loop
because series membership shifts SME scores.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.db.models.entities import Conference, ConferenceSeries
from app.db.session import DbSession
from app.services.series import (
    assign_conference_to_series,
    create_series,
    deactivate_series,
    suggest_series_for_unlinked,
    unassign_conference_from_series,
    update_series,
)

log = structlog.get_logger("scout.api.series")
router = APIRouter(prefix="/api/v1/conference-series", tags=["conference-series"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SeriesCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    canonical_name: str = Field(..., min_length=2, max_length=150)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=600)
    typical_month: int | None = Field(default=None, ge=1, le=12)
    typical_topics: list[str] = Field(default_factory=list, max_length=30)
    homepage: str | None = Field(default=None, max_length=500)


class SeriesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    canonical_name: str | None = Field(default=None, min_length=2, max_length=150)
    aliases: list[str] | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=600)
    typical_month: int | None = Field(default=None, ge=1, le=12)
    typical_topics: list[str] | None = Field(default=None, max_length=30)
    homepage: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class SeriesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: UUID
    canonical_name: str
    aliases: list[str]
    description: str
    typical_month: int | None
    typical_topics: list[str]
    homepage: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SeriesListItem(SeriesRead):
    """Listing row — includes member counts so the settings UI can render
    them in one call."""

    member_count: int


class AssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conference_id: UUID


# ---------------------------------------------------------------------------
# Listing + detail
# ---------------------------------------------------------------------------
@router.get("")
async def list_series(
    db: DbSession,
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """List series with their member-conference counts."""
    base = select(ConferenceSeries)
    if not include_inactive:
        base = base.where(ConferenceSeries.is_active.is_(True))
    base = base.order_by(ConferenceSeries.canonical_name.asc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    # One small aggregation for counts.
    counts = dict(
        (
            await db.execute(
                select(Conference.series_id, func.count(Conference.id))
                .where(Conference.series_id.is_not(None))
                .group_by(Conference.series_id)
            )
        ).all()
    )

    items = [
        SeriesListItem(
            **SeriesRead.model_validate(r).model_dump(),
            member_count=int(counts.get(r.id, 0)),
        )
        for r in rows
    ]
    return {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}


@router.get("/suggestions")
async def list_suggestions(
    db: DbSession,
    threshold: float = Query(default=0.55, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Run the detector + return ranked (conference, series, confidence)
    suggestions for human review."""
    suggestions = await suggest_series_for_unlinked(db, threshold=threshold, limit=limit)
    return {
        "threshold": threshold,
        "limit": limit,
        "suggestions": [s.to_dict() for s in suggestions],
    }


@router.get("/{series_id}")
async def get_series(db: DbSession, series_id: UUID) -> dict:
    """Series row + member conferences ordered by start_date."""
    row = await db.get(ConferenceSeries, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No conference_series {series_id}")

    members = (
        (
            await db.execute(
                select(Conference)
                .where(Conference.series_id == series_id)
                .order_by(Conference.start_date.asc().nullslast())
            )
        )
        .scalars()
        .all()
    )

    return {
        **SeriesRead.model_validate(row).model_dump(mode="json"),
        "members": [
            {
                "id": str(c.id),
                "name": c.name,
                "slug": c.slug,
                "status": c.status,
                "start_date": c.start_date.isoformat() if c.start_date else None,
            }
            for c in members
        ],
    }


# ---------------------------------------------------------------------------
# Create / update / deactivate
# ---------------------------------------------------------------------------
@router.post("", response_model=SeriesRead, status_code=status.HTTP_201_CREATED)
async def post_series(db: DbSession, payload: SeriesCreate) -> SeriesRead:
    row = await create_series(
        db,
        canonical_name=payload.canonical_name,
        aliases=payload.aliases,
        description=payload.description,
        typical_month=payload.typical_month,
        typical_topics=payload.typical_topics,
        homepage=payload.homepage,
        actor_label="api",
    )
    await db.commit()
    return SeriesRead.model_validate(row)


@router.patch("/{series_id}", response_model=SeriesRead)
async def patch_series(db: DbSession, series_id: UUID, payload: SeriesUpdate) -> SeriesRead:
    row = await update_series(
        db,
        series_id,
        canonical_name=payload.canonical_name,
        aliases=payload.aliases,
        description=payload.description,
        typical_month=payload.typical_month,
        typical_topics=payload.typical_topics,
        homepage=payload.homepage,
        is_active=payload.is_active,
        actor_label="api",
    )
    await db.commit()
    return SeriesRead.model_validate(row)


@router.delete("/{series_id}", status_code=status.HTTP_200_OK)
async def delete_series(db: DbSession, series_id: UUID) -> dict:
    row = await deactivate_series(db, series_id, actor_label="api")
    await db.commit()
    return {"id": str(row.id), "is_active": row.is_active}


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------
@router.post("/{series_id}/assign", status_code=status.HTTP_200_OK)
async def assign(db: DbSession, series_id: UUID, body: AssignBody) -> dict:
    """Link a conference to this series. Triggers a matcher recompute
    (past-attendance bonus may shift). Returns updated conference fields."""
    conf = await assign_conference_to_series(db, series_id, body.conference_id, actor_label="api")
    await db.commit()
    return {
        "conference_id": str(conf.id),
        "series_id": str(conf.series_id) if conf.series_id else None,
        "status": conf.status,
    }


@router.post("/{series_id}/unassign", status_code=status.HTTP_200_OK)
async def unassign(db: DbSession, series_id: UUID, body: AssignBody) -> dict:
    """Unlink a conference from any series. The ``series_id`` in the path
    is matched against the conference's current ``series_id`` and errors
    if they don't match — protects against stale UI re-submitting an old link.
    """
    conf = await db.get(Conference, body.conference_id)
    if conf is None:
        raise HTTPException(status_code=404, detail=f"No conference {body.conference_id}")
    if conf.series_id != series_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Conference {body.conference_id} is not linked to series "
                f"{series_id} (currently linked to {conf.series_id})."
            ),
        )
    conf = await unassign_conference_from_series(db, body.conference_id, actor_label="api")
    await db.commit()
    return {
        "conference_id": str(conf.id),
        "series_id": None,
        "status": conf.status,
    }
