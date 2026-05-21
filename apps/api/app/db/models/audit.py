"""Audit schema — append-only audit_log + content_versions.

These tables live in the ``audit`` schema. The ``app`` role has INSERT +
SELECT only (see ``infra/postgres/init/02-roles-and-schemas.sql``); UPDATE
and DELETE are blocked at the role level — defense in depth against
application bugs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import uuid_pk


class AuditLog(Base):
    """Append-only audit trail. NO TimestampedMixin: we use ``at`` as the
    canonical timestamp; ``created_at``/``updated_at`` don't apply to an
    append-only log."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_at", "at"),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    actor_label: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("'system'")
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ContentVersion(Base):
    """Git-blame-style change log for versioned entities (plan 25)."""

    __tablename__ = "content_versions"
    __table_args__ = (
        Index("ix_content_versions_entity", "entity_type", "entity_id"),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # jsonpatch
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False)

    actor_label: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("'system'")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    reason: Mapped[str | None] = mapped_column(Text)
