"""SMEs service.

Beyond the standard CRUD: FK existence checks against ``topics`` and
``audience_profiles`` happen here (the Pydantic schemas only validate UUID
shape; the DB doesn't have ON-INSERT FK constraints on the ``primary_topics``
and ``audience_focus`` array columns because they're denormalized).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import AudienceProfile, Sme, Topic
from app.db.models.junctions import SmeAudience, SmeTopic
from app.schemas.common import Page
from app.schemas.sme import SmeCreate, SmeRead, SmeUpdate
from app.services._common import model_to_audit_dict, paginate, write_audit
from app.services.embeddings import embed_owner
from app.services.graph import invalidate as invalidate_graph


async def _sync_sme_junctions(
    db: AsyncSession,
    sme_id: UUID,
    *,
    topic_ids: list[UUID],
    audience_ids: list[UUID],
) -> None:
    """Replace the SME's edges in ``sme_topics`` + ``sme_audiences``.

    The denormalized arrays on the SME row are the user-facing surface; the
    junctions are the graph's source of truth (plan 16). Keeping them in
    sync is a single delete-then-insert per call, which fits this tiny scale.
    """
    await db.execute(delete(SmeTopic).where(SmeTopic.sme_id == sme_id))
    await db.execute(delete(SmeAudience).where(SmeAudience.sme_id == sme_id))
    for tid in topic_ids:
        db.add(SmeTopic(sme_id=sme_id, topic_id=tid, weight=1.0))
    for aid in audience_ids:
        db.add(SmeAudience(sme_id=sme_id, audience_id=aid, weight=1.0))


log = structlog.get_logger("scout.services.sme")


async def _embed_bio_safely(db: AsyncSession, obj: Sme, *, purpose: str) -> None:
    """Embed the SME's bio. Failure leaves the row un-indexed; admin can retry."""
    try:
        await embed_owner(
            db,
            owner_type="sme_bio",
            owner_id=obj.id,
            text=obj.bio,
            purpose=purpose,
        )
        await db.commit()
    except Exception as exc:
        log.warning(
            "sme.embed_failed",
            sme_id=str(obj.id),
            error=f"{type(exc).__name__}: {exc}",
        )
        await db.rollback()


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

    await _sync_sme_junctions(
        db,
        obj.id,
        topic_ids=list(payload.primary_topics),
        audience_ids=list(payload.audience_focus),
    )

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
    invalidate_graph()  # SmeTopic / SmeAudience writes invalidated edges
    await _embed_bio_safely(db, obj, purpose="embed:sme_bio:create")
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
    # See audience_service.update_audience_profile: refresh after flush so
    # the next model_to_audit_dict access doesn't trip MissingGreenlet on
    # the expired onupdate=now() updated_at column.
    await db.refresh(obj)

    await _sync_sme_junctions(
        db,
        obj.id,
        topic_ids=list(payload.primary_topics),
        audience_ids=list(payload.audience_focus),
    )

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
    invalidate_graph()  # SmeTopic / SmeAudience may have changed
    await _embed_bio_safely(db, obj, purpose="embed:sme_bio:update")
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
    await db.refresh(obj)  # see update_sme

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
