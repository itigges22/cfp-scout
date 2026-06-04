"""/api/v1/talk-tags — talk tag CRUD."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.db.session import DbSession
from app.schemas.talk import TalkTagCreate, TalkTagRead, TalkTagUpdate
from app.services import talk_service

router = APIRouter(prefix="/api/v1/talk-tags", tags=["talk-tags"])


@router.get("", response_model=list[TalkTagRead])
async def list_(db: DbSession) -> list[TalkTagRead]:
    return await talk_service.list_tags(db)


@router.post("", response_model=TalkTagRead, status_code=status.HTTP_201_CREATED)
async def create_(db: DbSession, payload: TalkTagCreate) -> TalkTagRead:
    return await talk_service.create_tag(db, payload)


@router.put("/{tag_id}", response_model=TalkTagRead)
async def update_(db: DbSession, tag_id: UUID, payload: TalkTagUpdate) -> TalkTagRead:
    return await talk_service.update_tag(db, tag_id, payload)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_(db: DbSession, tag_id: UUID) -> None:
    await talk_service.delete_tag(db, tag_id)
