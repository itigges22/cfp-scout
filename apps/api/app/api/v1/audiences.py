"""/api/v1/audience-profiles routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.db.session import DbSession
from app.schemas.audience import (
    AudienceProfileCreate,
    AudienceProfileRead,
    AudienceProfileUpdate,
)
from app.schemas.common import Page
from app.services import audience_service

router = APIRouter(prefix="/api/v1/audience-profiles", tags=["audiences"])


@router.get("", response_model=Page[AudienceProfileRead])
async def list_(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: str | None = None,
    is_active: bool | None = None,
    pillar_id: UUID | None = None,
) -> Page[AudienceProfileRead]:
    return await audience_service.list_audience_profiles(
        db, page=page, per_page=per_page, q=q, is_active=is_active, pillar_id=pillar_id
    )


@router.get("/{aud_id}", response_model=AudienceProfileRead)
async def get_(db: DbSession, aud_id: UUID) -> AudienceProfileRead:
    obj = await audience_service.get_audience_profile(db, aud_id)
    return AudienceProfileRead.model_validate(obj)


@router.post(
    "",
    response_model=AudienceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_(
    db: DbSession,
    payload: AudienceProfileCreate,
    actor_label: str = Query("system"),
) -> AudienceProfileRead:
    obj = await audience_service.create_audience_profile(db, payload, actor_label=actor_label)
    return AudienceProfileRead.model_validate(obj)


@router.put("/{aud_id}", response_model=AudienceProfileRead)
async def update_(
    db: DbSession,
    aud_id: UUID,
    payload: AudienceProfileUpdate,
    actor_label: str = Query("system"),
) -> AudienceProfileRead:
    obj = await audience_service.update_audience_profile(
        db, aud_id, payload, actor_label=actor_label
    )
    return AudienceProfileRead.model_validate(obj)


@router.delete("/{aud_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_(
    db: DbSession,
    aud_id: UUID,
    actor_label: str = Query("system"),
) -> None:
    await audience_service.deactivate_audience_profile(db, aud_id, actor_label=actor_label)
