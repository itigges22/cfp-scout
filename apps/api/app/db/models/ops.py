"""Operational tables in the ``app`` schema.

ingest_jobs   — every scrape/match/decay run (plan 13)
llm_calls     — every LLM call; powers the budget guardrail (plan 10) and the /diagnostics LLM panel (plan 26)
chat_sessions, chat_messages — agent chat persistence (plan 22)
notifications — CFP-closing digest, etc. (plan 24)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import TimestampedMixin, uuid_pk


class IngestJob(TimestampedMixin, Base):
    """Each scrape, extraction, match, decay run lands a row here."""

    __tablename__ = "ingest_jobs"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_text: Mapped[str | None] = mapped_column(Text)


class LLMCall(Base):
    """Every LLM call. NO TimestampedMixin — we use ``created_at`` only
    (no UPDATE semantics for an append-only log)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_created_at", "created_at"),
        Index("ix_llm_calls_purpose", "purpose"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    model: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ChatSession(TimestampedMixin, Base):
    """Agent chat session. One conversation per row."""

    __tablename__ = "chat_sessions"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    title: Mapped[str | None] = mapped_column(String(200))
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class ChatMessage(Base):
    """One turn (user or assistant) in a chat_session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session", "session_id", "created_at"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Citations + intent classification + token usage
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Notification(Base):
    """In-app notifications (bell badge). Plan 24 owns the CFP-closing digest."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_unread", "seen", "created_at"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    seen: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AppSettingOverride(Base):
    """Singleton-style key/value overrides for app/settings.py values.

    Populated via ``PATCH /api/v1/admin/settings`` so admins can tune
    matcher weights, decay flags, LLM keys/models/budget, etc. without
    editing ``.env``. This table is the runtime source of truth: env vars
    are boot defaults only. Loaded into the Pydantic Settings instance at
    startup, then re-read every ``settings_refresh_seconds`` by every
    process (api replicas + standalone scheduler, see
    ``app.services.settings_refresh``), so a PATCH — including an
    LLM_API_KEY rotation — propagates everywhere without a restart.
    """

    __tablename__ = "app_setting_overrides"
    __table_args__ = {"schema": "app"}

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded scalar/list
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actor_label: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("'system'")
    )
