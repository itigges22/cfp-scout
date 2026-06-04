"""Pillar service — CRUD for strategic pillars + content roadmap + GTM strategy."""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    AudienceProfile,
    Conference,
    PillarContentRoadmap,
    PillarGtmStrategy,
    Sme,
    StrategicPillar,
    Talk,
)
from app.db.models.junctions import SmePillar
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

log = structlog.get_logger("scout.services.pillar")


async def _get_pillar_or_404(db: AsyncSession, pillar_id: UUID) -> StrategicPillar:
    obj = await db.get(StrategicPillar, pillar_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pillar {pillar_id} not found",
        )
    return obj


async def _build_pillar_read(db: AsyncSession, p: StrategicPillar) -> PillarRead:
    """Attach aggregate counts to a pillar row."""
    sme_count = (
        await db.execute(select(func.count()).where(SmePillar.pillar_id == p.id))
    ).scalar_one()
    talk_count = (
        await db.execute(
            select(func.count()).where(Talk.pillar_id == p.id, Talk.is_active.is_(True))
        )
    ).scalar_one()
    audience_count = (
        await db.execute(
            select(func.count()).where(
                AudienceProfile.pillar_id == p.id, AudienceProfile.is_active.is_(True)
            )
        )
    ).scalar_one()
    conference_count = (
        await db.execute(
            select(func.count()).where(Conference.assigned_pillar_id == p.id)
        )
    ).scalar_one()

    data = PillarRead.model_validate(p)
    data.sme_count = int(sme_count)
    data.talk_count = int(talk_count)
    data.audience_count = int(audience_count)
    data.conference_count = int(conference_count)
    return data


async def delete_pillar(db: AsyncSession, pillar_id: UUID) -> None:
    p = await _get_pillar_or_404(db, pillar_id)
    await db.delete(p)
    await db.commit()


async def create_pillar(db: AsyncSession, payload: PillarCreate) -> PillarRead:
    max_order = (
        await db.execute(select(func.max(StrategicPillar.display_order)))
    ).scalar_one()
    order = (max_order or 0) + 1 if payload.display_order is None else payload.display_order
    p = StrategicPillar(name=payload.name, description=payload.description, display_order=order)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return await _build_pillar_read(db, p)


async def list_pillars(db: AsyncSession) -> list[PillarRead]:
    rows = (
        await db.execute(select(StrategicPillar).order_by(StrategicPillar.display_order))
    ).scalars().all()
    return [await _build_pillar_read(db, p) for p in rows]


async def get_pillar(db: AsyncSession, pillar_id: UUID) -> PillarRead:
    p = await _get_pillar_or_404(db, pillar_id)
    return await _build_pillar_read(db, p)


async def update_pillar(db: AsyncSession, pillar_id: UUID, payload: PillarUpdate) -> PillarRead:
    p = await _get_pillar_or_404(db, pillar_id)
    p.name = payload.name
    p.description = payload.description
    await db.commit()
    await db.refresh(p)
    return await _build_pillar_read(db, p)


# ---------------------------------------------------------------------------
# SME ↔ pillar linking
# ---------------------------------------------------------------------------


async def link_sme(
    db: AsyncSession, pillar_id: UUID, sme_id: UUID, payload: SmePillarLink
) -> SmePillarRead:
    await _get_pillar_or_404(db, pillar_id)
    sme = await db.get(Sme, sme_id)
    if sme is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"sme {sme_id} not found")

    existing = await db.get(SmePillar, (sme_id, pillar_id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="sme already linked to this pillar",
        )
    row = SmePillar(sme_id=sme_id, pillar_id=pillar_id, is_primary=payload.is_primary)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return SmePillarRead.model_validate(row)


async def unlink_sme(db: AsyncSession, pillar_id: UUID, sme_id: UUID) -> None:
    row = await db.get(SmePillar, (sme_id, pillar_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="sme not linked to this pillar",
        )
    await db.delete(row)
    await db.commit()


async def list_pillar_smes(db: AsyncSession, pillar_id: UUID) -> list[SmePillarRead]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        await db.execute(
            select(SmePillar)
            .where(SmePillar.pillar_id == pillar_id)
            .order_by(SmePillar.is_primary.desc())
        )
    ).scalars().all()
    return [SmePillarRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Content roadmap
# ---------------------------------------------------------------------------


async def list_roadmap_entries(db: AsyncSession, pillar_id: UUID) -> list[RoadmapEntryRead]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        await db.execute(
            select(PillarContentRoadmap)
            .where(PillarContentRoadmap.pillar_id == pillar_id)
            .order_by(PillarContentRoadmap.created_at.desc())
        )
    ).scalars().all()
    return [RoadmapEntryRead.model_validate(r) for r in rows]


async def add_roadmap_entry(
    db: AsyncSession, pillar_id: UUID, payload: RoadmapEntryCreate
) -> RoadmapEntryRead:
    await _get_pillar_or_404(db, pillar_id)
    row = PillarContentRoadmap(
        pillar_id=pillar_id,
        quarter=payload.quarter,
        goals=payload.goals,
        owner_label=payload.owner_label,
        notes=payload.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return RoadmapEntryRead.model_validate(row)


async def update_roadmap_entry(
    db: AsyncSession, pillar_id: UUID, roadmap_id: UUID, payload: RoadmapEntryUpdate
) -> RoadmapEntryRead:
    await _get_pillar_or_404(db, pillar_id)
    row = await db.get(PillarContentRoadmap, roadmap_id)
    if row is None or row.pillar_id != pillar_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="roadmap entry not found")
    if payload.quarter is not None:
        row.quarter = payload.quarter
    if payload.goals is not None:
        row.goals = payload.goals
    if payload.owner_label is not None:
        row.owner_label = payload.owner_label
    if payload.notes is not None:
        row.notes = payload.notes
    await db.commit()
    await db.refresh(row)
    return RoadmapEntryRead.model_validate(row)


async def delete_roadmap_entry(db: AsyncSession, pillar_id: UUID, roadmap_id: UUID) -> None:
    await _get_pillar_or_404(db, pillar_id)
    row = await db.get(PillarContentRoadmap, roadmap_id)
    if row is None or row.pillar_id != pillar_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="roadmap entry not found")
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# GTM strategy
# ---------------------------------------------------------------------------


async def create_gtm_strategy(
    db: AsyncSession, pillar_id: UUID, payload: GtmStrategyCreate
) -> GtmStrategyRead:
    await _get_pillar_or_404(db, pillar_id)
    # Find current max version for this pillar
    max_version = (
        await db.execute(
            select(func.max(PillarGtmStrategy.version)).where(
                PillarGtmStrategy.pillar_id == pillar_id
            )
        )
    ).scalar_one()
    next_version = (max_version or 0) + 1

    row = PillarGtmStrategy(
        pillar_id=pillar_id,
        objective=payload.objective,
        key_messages=payload.key_messages,
        target_audience_ids=payload.target_audience_ids,
        notes=payload.notes,
        version=next_version,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return GtmStrategyRead.model_validate(row)


async def list_gtm_strategies(db: AsyncSession, pillar_id: UUID) -> list[GtmStrategyRead]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        await db.execute(
            select(PillarGtmStrategy)
            .where(PillarGtmStrategy.pillar_id == pillar_id)
            .order_by(PillarGtmStrategy.version.desc())
        )
    ).scalars().all()
    return [GtmStrategyRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Pillar-scoped lists
# ---------------------------------------------------------------------------


async def list_pillar_conferences(
    db: AsyncSession, pillar_id: UUID
) -> list[dict]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        await db.execute(
            select(Conference).where(Conference.assigned_pillar_id == pillar_id)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "slug": r.slug,
            "status": r.status,
            "event_kind": r.event_kind,
        }
        for r in rows
    ]


async def list_pillar_talks(db: AsyncSession, pillar_id: UUID) -> list[dict]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        await db.execute(
            select(Talk).where(Talk.pillar_id == pillar_id, Talk.is_active.is_(True))
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "review_status": r.review_status,
        }
        for r in rows
    ]


async def list_pillar_audiences(db: AsyncSession, pillar_id: UUID) -> list[dict]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        await db.execute(
            select(AudienceProfile).where(
                AudienceProfile.pillar_id == pillar_id,
                AudienceProfile.is_active.is_(True),
            )
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
        }
        for r in rows
    ]
