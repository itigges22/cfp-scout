"""/api/v1/pillars — pillar CRUD + content roadmap + GTM strategy + SME links."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.db.session import DbSession
from app.schemas.pillar import (
    GtmStrategyCreate,
    GtmStrategyRead,
    PillarCreate,
    PillarRead,
    PillarUpdate,
    RoadmapEntryCreate,
    RoadmapEntryRead,
    RoadmapEntryUpdate,
    SmePillarLink,
    SmePillarRead,
)
from app.services import pillar_service

router = APIRouter(prefix="/api/v1/pillars", tags=["pillars"])



@router.get("", response_model=list[PillarRead])
async def list_(db: DbSession) -> list[PillarRead]:
    return await pillar_service.list_pillars(db)


@router.post("", response_model=PillarRead, status_code=status.HTTP_201_CREATED)
async def create_(db: DbSession, payload: PillarCreate) -> PillarRead:
    return await pillar_service.create_pillar(db, payload)


@router.get("/{pillar_id}", response_model=PillarRead)
async def get_(db: DbSession, pillar_id: UUID) -> PillarRead:
    return await pillar_service.get_pillar(db, pillar_id)


@router.put("/{pillar_id}", response_model=PillarRead)
async def update_(db: DbSession, pillar_id: UUID, payload: PillarUpdate) -> PillarRead:
    return await pillar_service.update_pillar(db, pillar_id, payload)


@router.delete("/{pillar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_(db: DbSession, pillar_id: UUID) -> None:
    await pillar_service.delete_pillar(db, pillar_id)


# ---------------------------------------------------------------------------
# SME linking
# ---------------------------------------------------------------------------


@router.post(
    "/{pillar_id}/smes/{sme_id}",
    response_model=SmePillarRead,
    status_code=status.HTTP_201_CREATED,
)
async def link_sme(
    db: DbSession, pillar_id: UUID, sme_id: UUID, payload: SmePillarLink
) -> SmePillarRead:
    return await pillar_service.link_sme(db, pillar_id, sme_id, payload)


@router.delete("/{pillar_id}/smes/{sme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_sme(db: DbSession, pillar_id: UUID, sme_id: UUID) -> None:
    await pillar_service.unlink_sme(db, pillar_id, sme_id)


@router.get("/{pillar_id}/smes", response_model=list[SmePillarRead])
async def list_smes(db: DbSession, pillar_id: UUID) -> list[SmePillarRead]:
    return await pillar_service.list_pillar_smes(db, pillar_id)


# ---------------------------------------------------------------------------
# Content roadmap
# ---------------------------------------------------------------------------


@router.get("/{pillar_id}/content-roadmap", response_model=list[RoadmapEntryRead])
async def list_roadmap(db: DbSession, pillar_id: UUID) -> list[RoadmapEntryRead]:
    return await pillar_service.list_roadmap_entries(db, pillar_id)


@router.post(
    "/{pillar_id}/content-roadmap",
    response_model=RoadmapEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_roadmap(
    db: DbSession, pillar_id: UUID, payload: RoadmapEntryCreate
) -> RoadmapEntryRead:
    return await pillar_service.add_roadmap_entry(db, pillar_id, payload)


@router.put("/{pillar_id}/content-roadmap/{roadmap_id}", response_model=RoadmapEntryRead)
async def update_roadmap(
    db: DbSession, pillar_id: UUID, roadmap_id: UUID, payload: RoadmapEntryUpdate
) -> RoadmapEntryRead:
    return await pillar_service.update_roadmap_entry(db, pillar_id, roadmap_id, payload)


@router.delete(
    "/{pillar_id}/content-roadmap/{roadmap_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_roadmap(db: DbSession, pillar_id: UUID, roadmap_id: UUID) -> None:
    await pillar_service.delete_roadmap_entry(db, pillar_id, roadmap_id)


# ---------------------------------------------------------------------------
# GTM strategy
# ---------------------------------------------------------------------------


@router.post(
    "/{pillar_id}/gtm-strategy",
    response_model=GtmStrategyRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_gtm(
    db: DbSession, pillar_id: UUID, payload: GtmStrategyCreate
) -> GtmStrategyRead:
    return await pillar_service.create_gtm_strategy(db, pillar_id, payload)


@router.get("/{pillar_id}/gtm-strategy", response_model=list[GtmStrategyRead])
async def list_gtm(db: DbSession, pillar_id: UUID) -> list[GtmStrategyRead]:
    return await pillar_service.list_gtm_strategies(db, pillar_id)


# ---------------------------------------------------------------------------
# Pillar-scoped collections
# ---------------------------------------------------------------------------


@router.get("/{pillar_id}/conferences")
async def list_conferences(db: DbSession, pillar_id: UUID) -> list[dict]:
    return await pillar_service.list_pillar_conferences(db, pillar_id)


@router.get("/{pillar_id}/talks")
async def list_talks(db: DbSession, pillar_id: UUID) -> list[dict]:
    return await pillar_service.list_pillar_talks(db, pillar_id)


@router.get("/{pillar_id}/audiences")
async def list_audiences(db: DbSession, pillar_id: UUID) -> list[dict]:
    return await pillar_service.list_pillar_audiences(db, pillar_id)
