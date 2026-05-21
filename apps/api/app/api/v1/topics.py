"""/api/v1/topics routes — admin curation of the controlled vocabulary."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.db.session import DbSession
from app.schemas.common import Page
from app.schemas.topic import TopicCreate, TopicRead, TopicUpdate
from app.services import topic_service

router = APIRouter(prefix="/api/v1/topics", tags=["topics"])


@router.get("", response_model=Page[TopicRead])
async def list_(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    pending_only: bool | None = Query(
        None, description="True = only pending_review topics; False = exclude them; null = all."
    ),
    q: str | None = None,
) -> Page[TopicRead]:
    return await topic_service.list_topics(
        db, page=page, per_page=per_page, pending_only=pending_only, q=q
    )


@router.get("/{topic_id}", response_model=TopicRead)
async def get_(db: DbSession, topic_id: UUID) -> TopicRead:
    obj = await topic_service.get_topic(db, topic_id)
    return TopicRead.model_validate(obj)


@router.post("", response_model=TopicRead, status_code=status.HTTP_201_CREATED)
async def create_(
    db: DbSession,
    payload: TopicCreate,
    actor_label: str = Query("system"),
) -> TopicRead:
    obj = await topic_service.create_topic(db, payload, actor_label=actor_label)
    return TopicRead.model_validate(obj)


@router.put("/{topic_id}", response_model=TopicRead)
async def update_(
    db: DbSession,
    topic_id: UUID,
    payload: TopicUpdate,
    actor_label: str = Query("system"),
) -> TopicRead:
    obj = await topic_service.update_topic(db, topic_id, payload, actor_label=actor_label)
    return TopicRead.model_validate(obj)


@router.post("/{topic_id}/approve", response_model=TopicRead)
async def approve_(
    db: DbSession,
    topic_id: UUID,
    actor_label: str = Query("system"),
) -> TopicRead:
    """Promote a pending LLM-discovered topic into the active vocabulary."""
    obj = await topic_service.approve_topic(db, topic_id, actor_label=actor_label)
    return TopicRead.model_validate(obj)


@router.post("/{topic_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_(
    db: DbSession,
    topic_id: UUID,
    actor_label: str = Query("system"),
) -> None:
    """Reject a pending topic. Stays in DB (for audit) but is_active=false
    so it never enters the matcher."""
    await topic_service.reject_topic(db, topic_id, actor_label=actor_label)
