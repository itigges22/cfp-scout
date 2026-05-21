"""/api/v1/smes routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.db.session import DbSession
from app.schemas.common import Page
from app.schemas.sme import SmeCreate, SmeRead, SmeUpdate
from app.services import sme_service

router = APIRouter(prefix="/api/v1/smes", tags=["smes"])


@router.get("", response_model=Page[SmeRead])
async def list_(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: str | None = None,
    team: str | None = None,
    is_active: bool | None = None,
) -> Page[SmeRead]:
    return await sme_service.list_smes(
        db, page=page, per_page=per_page, q=q, team=team, is_active=is_active
    )


@router.get("/{sme_id}", response_model=SmeRead)
async def get_(db: DbSession, sme_id: UUID) -> SmeRead:
    obj = await sme_service.get_sme(db, sme_id)
    return SmeRead.model_validate(obj)


@router.post("", response_model=SmeRead, status_code=status.HTTP_201_CREATED)
async def create_(
    db: DbSession,
    payload: SmeCreate,
    actor_label: str = Query("system"),
) -> SmeRead:
    obj = await sme_service.create_sme(db, payload, actor_label=actor_label)
    return SmeRead.model_validate(obj)


@router.put("/{sme_id}", response_model=SmeRead)
async def update_(
    db: DbSession,
    sme_id: UUID,
    payload: SmeUpdate,
    actor_label: str = Query("system"),
) -> SmeRead:
    obj = await sme_service.update_sme(db, sme_id, payload, actor_label=actor_label)
    return SmeRead.model_validate(obj)


@router.delete("/{sme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_(
    db: DbSession,
    sme_id: UUID,
    actor_label: str = Query("system"),
) -> None:
    await sme_service.deactivate_sme(db, sme_id, actor_label=actor_label)
