"""SMEs service.

Beyond the standard CRUD: FK existence checks against ``topics`` and
``audience_profiles`` happen here (the Pydantic schemas only validate UUID
shape; the DB doesn't have ON-INSERT FK constraints on the ``primary_topics``
and ``audience_focus`` array columns because they're denormalized).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import AudienceProfile, Sme, Topic
from app.schemas.common import Page
from app.schemas.sme import SmeCreate, SmeRead, SmeUpdate
from app.services._common import model_to_audit_dict, paginate, write_audit


async def _check_topic_ids(db: AsyncSession, ids: list[UUID]) -> None:
    if not ids:
        return
    count = (
        await db.execute(
            select(func.count(Topic.id)).where(Topic.id.in_(ids), Topic.is_active.is_(True))
        )
    ).scalar_one()
    if int(count) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="one or more primary_topics ids do not exist or are inactive",
        )


async def _check_audience_ids(db: AsyncSession, ids: list[UUID]) -> None:
    if not ids:
        return
    count = (
        await db.execute(
            select(func.count(AudienceProfile.id)).where(
                AudienceProfile.id.in_(ids),
                AudienceProfile.is_active.is_(True),
            )
        )
    ).scalar_one()
    if int(count) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="one or more audience_focus ids do not exist or are inactive",
        )


async def list_smes(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    q: str | None = None,
    team: str | None = None,
    is_active: bool | None = None,
) -> Page[SmeRead]:
    stmt = select(Sme).order_by(Sme.full_name.asc())
    if q:
        stmt = stmt.where(Sme.full_name.ilike(f"%{q}%"))
    if team:
        stmt = stmt.where(Sme.team == team)
    if is_active is not None:
        stmt = stmt.where(Sme.is_active.is_(is_active))

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[SmeRead](
        items=[SmeRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_sme(db: AsyncSession, sme_id: UUID) -> Sme:
    obj = await db.get(Sme, sme_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"sme {sme_id} not found",
        )
    return obj


async def create_sme(
    db: AsyncSession,
    payload: SmeCreate,
    *,
    actor_label: str = "system",
) -> Sme:
    # FK existence checks on the denormalized array columns.
    await _check_topic_ids(db, payload.primary_topics)
    await _check_audience_ids(db, payload.audience_focus)

    data = payload.model_dump()
    # external_links is a Pydantic model; flatten to dict for JSONB column.
    data["external_links"] = payload.external_links.model_dump(exclude_none=True)

    obj = Sme(**data)
    db.add(obj)
    await db.flush()

    await write_audit(
        db,
        action="create",
        target_type="sme",
        target_id=obj.id,
        before=None,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def update_sme(
    db: AsyncSession,
    sme_id: UUID,
    payload: SmeUpdate,
    *,
    actor_label: str = "system",
) -> Sme:
    obj = await get_sme(db, sme_id)
    before = model_to_audit_dict(obj)

    await _check_topic_ids(db, payload.primary_topics)
    await _check_audience_ids(db, payload.audience_focus)

    data = payload.model_dump()
    data["external_links"] = payload.external_links.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(obj, key, value)
    await db.flush()

    await write_audit(
        db,
        action="update",
        target_type="sme",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def deactivate_sme(
    db: AsyncSession,
    sme_id: UUID,
    *,
    actor_label: str = "system",
) -> None:
    obj = await get_sme(db, sme_id)
    if not obj.is_active:
        return

    before = model_to_audit_dict(obj)
    obj.is_active = False
    await db.flush()

    await write_audit(
        db,
        action="deactivate",
        target_type="sme",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
