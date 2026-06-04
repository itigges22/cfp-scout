"""Audience-profiles service. Same shape as messaging."""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import AudienceProfile
from app.schemas.audience import (
    AudienceProfileCreate,
    AudienceProfileRead,
    AudienceProfileUpdate,
)
from app.schemas.common import Page
from app.services._common import model_to_audit_dict, paginate, write_audit
from app.services.embeddings import embed_owner

log = structlog.get_logger("scout.services.audience")


def _audience_embed_text(a: AudienceProfile) -> str:
    """Compose the text we embed for similarity search against this profile."""
    parts = [
        a.name,
        a.description,
        f"Industry: {a.industry}",
        f"Seniority: {a.role_seniority}",
        "Pain points: " + "; ".join(a.primary_pain_points),
        "Key messages: " + "; ".join(a.key_messages),
    ]
    if a.exclusion_criteria:
        parts.append("Exclusion: " + "; ".join(a.exclusion_criteria))
    return "\n".join(parts)


async def _embed_safely(db: AsyncSession, obj: AudienceProfile, *, purpose: str) -> None:
    """Embed in a separate logical step. Failure leaves the entity un-indexed
    but the row persists; admin can re-trigger via /admin/embeddings/embed-owner."""
    try:
        await embed_owner(
            db,
            owner_type="audience",
            owner_id=obj.id,
            text=_audience_embed_text(obj),
            purpose=purpose,
        )
        await db.commit()
    except Exception as exc:
        log.warning(
            "audience.embed_failed",
            audience_id=str(obj.id),
            error=f"{type(exc).__name__}: {exc}",
        )
        await db.rollback()


async def list_audience_profiles(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    q: str | None = None,
    is_active: bool | None = None,
    pillar_id: UUID | None = None,
) -> Page[AudienceProfileRead]:
    stmt = select(AudienceProfile).order_by(AudienceProfile.name.asc())
    if q:
        stmt = stmt.where(AudienceProfile.name.ilike(f"%{q}%"))
    if is_active is not None:
        stmt = stmt.where(AudienceProfile.is_active.is_(is_active))
    if pillar_id is not None:
        stmt = stmt.where(AudienceProfile.pillar_id == pillar_id)

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[AudienceProfileRead](
        items=[AudienceProfileRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_audience_profile(db: AsyncSession, aud_id: UUID) -> AudienceProfile:
    obj = await db.get(AudienceProfile, aud_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"audience_profile {aud_id} not found",
        )
    return obj


async def create_audience_profile(
    db: AsyncSession,
    payload: AudienceProfileCreate,
    *,
    actor_label: str = "system",
) -> AudienceProfile:
    obj = AudienceProfile(**payload.model_dump())
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"audience_profile with name '{payload.name}' already exists",
        ) from exc

    await write_audit(
        db,
        action="create",
        target_type="audience_profile",
        target_id=obj.id,
        before=None,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_safely(db, obj, purpose="embed:audience:create")
    return obj


async def update_audience_profile(
    db: AsyncSession,
    aud_id: UUID,
    payload: AudienceProfileUpdate,
    *,
    actor_label: str = "system",
) -> AudienceProfile:
    obj = await get_audience_profile(db, aud_id)
    before = model_to_audit_dict(obj)

    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    await db.flush()
    # TimestampedMixin.updated_at has onupdate=func.now(); flush expires it
    # so a synchronous model_to_audit_dict access would trip MissingGreenlet.
    await db.refresh(obj)

    await write_audit(
        db,
        action="update",
        target_type="audience_profile",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_safely(db, obj, purpose="embed:audience:update")
    return obj


async def deactivate_audience_profile(
    db: AsyncSession,
    aud_id: UUID,
    *,
    actor_label: str = "system",
) -> None:
    obj = await get_audience_profile(db, aud_id)
    if not obj.is_active:
        return

    before = model_to_audit_dict(obj)
    obj.is_active = False
    await db.flush()
    await db.refresh(obj)  # see update_audience_profile

    await write_audit(
        db,
        action="deactivate",
        target_type="audience_profile",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
