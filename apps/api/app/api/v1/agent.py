"""/api/v1/agent — the chat assistant's sessions and messages.

WHAT THIS DOES
    A retrieval-augmented chat surface over Scout's own data. Sessions are
    created, listed, renamed and archived through ``/agent/sessions*``.
    ``GET /sessions/{id}/messages`` returns the transcript, and
    ``POST /sessions/{id}/messages`` asks a question: it persists both the
    user turn and the assistant turn and returns the reply with citations
    and token cost. The request body can narrow retrieval to certain
    ``owner_types`` and set ``k``, how many chunks get pulled in.

HOW IT CONNECTS
    Called by   main.py (registered as a router); the web UI calls
                /agent/sessions from apps/web/src/lib/api.ts
    Reads/writes app.chat_sessions, app.chat_messages
    Answers via services/agent/, which searches vectors.document_chunks and
                logs each provider call to app.llm_calls

WORTH KNOWING
    DELETE on a session archives it. Hard delete is intentionally not
    exposed so the app.chat_messages audit trail stays complete.
    An ask returns 404 for a missing session, 409 for an archived one, and
    503 once the monthly LLM budget cap is hit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.models import ChatMessage, ChatSession
from app.db.session import DbSession
from app.services.agent import ask
from app.services.embeddings import OWNER_TYPES
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
    # Narrow retrieval to a subset of owner types. Default = all of them.
    #
    # Derived from OWNER_TYPES rather than listed. The hand-written list here
    # accepted "pillar" and "raw_page", neither of which anything has ever
    # written — so a request naming one returned zero snippets and the agent
    # answered from nothing, with no error to explain why.
    owner_types: list[Literal[OWNER_TYPES]] | None = Field(  # type: ignore[valid-type]
        default=None
    )
    k: int = Field(default=16, ge=1, le=40)


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
