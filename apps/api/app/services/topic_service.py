"""Topics service. Admin-curated controlled vocabulary.

LLM-discovered topics (plan 15) land with ``is_active=false``,
``pending_review=true``. They do not influence matching until an admin
approves them — that's what the ``approve``/``reject`` actions below do.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Topic
from app.schemas.common import Page
from app.schemas.topic import TopicCreate, TopicRead, TopicUpdate
from app.services._common import model_to_audit_dict, paginate, write_audit


async def list_topics(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 50,
    pending_only: bool | None = None,
    q: str | None = None,
) -> Page[TopicRead]:
    stmt = select(Topic).order_by(Topic.name.asc())
    if pending_only is True:
        stmt = stmt.where(Topic.pending_review.is_(True))
    elif pending_only is False:
        stmt = stmt.where(Topic.pending_review.is_(False))
    if q:
        stmt = stmt.where(Topic.name.ilike(f"%{q}%"))

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[TopicRead](
        items=[TopicRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_topic(db: AsyncSession, topic_id: UUID) -> Topic:
    obj = await db.get(Topic, topic_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"topic {topic_id} not found",
        )
    return obj


async def create_topic(
    db: AsyncSession,
    payload: TopicCreate,
    *,
    actor_label: str = "system",
) -> Topic:
    data = payload.model_dump()
    # Auto-derive slug if absent.
    if not data.get("slug"):
        from app.schemas.topic import _slugify_lower

        data["slug"] = _slugify_lower(data["name"])

    obj = Topic(**data)
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"topic with name or slug already exists",
        ) from exc

    await write_audit(
        db,
        action="create",
        target_type="topic",
        target_id=obj.id,
        before=None,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def update_topic(
    db: AsyncSession,
    topic_id: UUID,
    payload: TopicUpdate,
    *,
    actor_label: str = "system",
) -> Topic:
    obj = await get_topic(db, topic_id)
    before = model_to_audit_dict(obj)

    data = payload.model_dump()
    if not data.get("slug"):
        from app.schemas.topic import _slugify_lower

        data["slug"] = _slugify_lower(data["name"])

    for key, value in data.items():
        setattr(obj, key, value)
    await db.flush()
    # See audience_service.update_audience_profile for the rationale.
    await db.refresh(obj)

    await write_audit(
        db,
        action="update",
        target_type="topic",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def approve_topic(
    db: AsyncSession,
    topic_id: UUID,
    *,
    actor_label: str = "system",
) -> Topic:
    """Approve a pending LLM-discovered topic: pending_review=false, is_active=true."""
    obj = await get_topic(db, topic_id)
    before = model_to_audit_dict(obj)

    obj.pending_review = False
    obj.is_active = True
    await db.flush()
    await db.refresh(obj)  # see update_topic

    await write_audit(
        db,
        action="approve",
        target_type="topic",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def reject_topic(
    db: AsyncSession,
    topic_id: UUID,
    *,
    actor_label: str = "system",
) -> None:
    """Reject a pending topic: deactivate + leave pending_review=true so it
    doesn't re-appear in the queue. Audit-logged for traceability."""
    obj = await get_topic(db, topic_id)
    before = model_to_audit_dict(obj)

    obj.is_active = False
    await db.flush()
    await db.refresh(obj)  # see update_topic

    await write_audit(
        db,
        action="reject",
        target_type="topic",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
