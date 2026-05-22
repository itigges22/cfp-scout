"""/api/v1/agent — chat sessions + per-turn asks (plan 22).

Endpoints:
  * ``POST   /agent/sessions``                  — create a new session
  * ``GET    /agent/sessions``                  — list active sessions
  * ``GET    /agent/sessions/{id}``             — session metadata
  * ``GET    /agent/sessions/{id}/messages``    — full message history
  * ``POST   /agent/sessions/{id}/messages``    — ask a question; returns reply
  * ``PATCH  /agent/sessions/{id}``             — rename / archive
  * ``DELETE /agent/sessions/{id}``             — soft delete (archives)

SSE streaming, slash commands, and the conversation sidebar live in pass 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.models.ops import ChatMessage, ChatSession
from app.db.session import DbSession
from app.services.agent import ask
from app.services.llm import BudgetExceeded

log = structlog.get_logger("scout.api.agent")
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChatSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, max_length=200)


class ChatSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: UUID
    title: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: UUID
    session_id: UUID
    role: str
    content: str
    metadata_json: dict
    created_at: datetime


class AskBody(BaseModel):
    """POST /agent/sessions/{id}/messages payload."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(..., min_length=1, max_length=4000)
    # Allow narrowing retrieval to a subset of owner_types. Default = all.
    owner_types: (
        list[Literal["conference", "messaging", "sme_bio", "audience", "pillar", "raw_page"]] | None
    ) = Field(default=None)
    k: int = Field(default=6, ge=1, le=20)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@router.post(
    "/sessions",
    response_model=ChatSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(db: DbSession, payload: ChatSessionCreate) -> ChatSessionRead:
    row = ChatSession(title=payload.title)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await db.commit()
    log.info("agent.session.created", session_id=str(row.id))
    return ChatSessionRead.model_validate(row)


@router.get("/sessions")
async def list_sessions(
    db: DbSession,
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    stmt = select(ChatSession).order_by(ChatSession.updated_at.desc()).limit(limit)
    if not include_archived:
        stmt = stmt.where(ChatSession.archived.is_(False))
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "sessions": [ChatSessionRead.model_validate(r).model_dump(mode="json") for r in rows],
    }


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
async def get_session(db: DbSession, session_id: UUID) -> ChatSessionRead:
    row = await db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No chat_session {session_id}")
    return ChatSessionRead.model_validate(row)


@router.patch("/sessions/{session_id}", response_model=ChatSessionRead)
async def update_session(
    db: DbSession, session_id: UUID, payload: ChatSessionUpdate
) -> ChatSessionRead:
    row = await db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No chat_session {session_id}")
    if payload.title is not None:
        row.title = payload.title
    if payload.archived is not None:
        row.archived = payload.archived
    await db.flush()
    await db.refresh(row)
    await db.commit()
    return ChatSessionRead.model_validate(row)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_200_OK)
async def delete_session(db: DbSession, session_id: UUID) -> dict:
    """Soft delete: archive the session. Hard delete is intentionally not
    exposed — the audit trail (chat_messages) stays usable."""
    row = await db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No chat_session {session_id}")
    row.archived = True
    await db.flush()
    await db.commit()
    return {"id": str(row.id), "archived": True}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
@router.get("/sessions/{session_id}/messages")
async def list_messages(db: DbSession, session_id: UUID) -> dict:
    if await db.get(ChatSession, session_id) is None:
        raise HTTPException(status_code=404, detail=f"No chat_session {session_id}")
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "session_id": str(session_id),
        "messages": [ChatMessageRead.model_validate(r).model_dump(mode="json") for r in rows],
    }


@router.post(
    "/sessions/{session_id}/messages",
    status_code=status.HTTP_201_CREATED,
)
async def post_message(db: DbSession, session_id: UUID, payload: AskBody) -> dict:
    """Ask a question. Persists user + assistant messages, returns reply +
    citations + token cost. Errors:
      * 404 if session doesn't exist
      * 409 if session is archived
      * 503 if the monthly budget cap is exceeded
    """
    try:
        reply = await ask(
            db,
            session_id=session_id,
            user_message=payload.content,
            owner_types=payload.owner_types,
            k=payload.k,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BudgetExceeded as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await db.commit()
    return reply.to_dict()
