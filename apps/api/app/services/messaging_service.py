"""Messaging-documents service.

Plan 09 surface: list / get / create / update / soft-delete.
Plan 11 wires post-commit embedding via ``_embed_safely``.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import MessagingDocument
from app.schemas.common import Page
from app.schemas.messaging import (
    MessagingDocumentCreate,
    MessagingDocumentRead,
    MessagingDocumentUpdate,
)
from app.services._common import model_to_audit_dict, paginate, write_audit
from app.services.embeddings import embed_owner

log = structlog.get_logger("scout.services.messaging")


def _messaging_embed_text(m: MessagingDocument) -> str:
    """Compose the text we embed for similarity search against this messaging doc.

    The structured fields are joined into a single document so the matcher's
    Stage A (messaging similarity) can hit any of them.
    """
    parts = [
        m.title,
        m.elevator_pitch,
        "Target personas: " + "; ".join(m.target_personas),
        "Key themes: " + "; ".join(m.key_themes),
        "Talking points: " + "; ".join(m.talking_points),
    ]
    if m.differentiators:
        parts.append("Differentiators: " + "; ".join(m.differentiators))
    if m.competitive_position:
        parts.append(f"Competitive position: {m.competitive_position}")
    if m.raw_content:
        # PDF-source docs have raw_content populated by plan 12; include it
        # so chunking can split across the body too.
        parts.append(m.raw_content)
    return "\n".join(parts)


async def _embed_safely(db: AsyncSession, obj: MessagingDocument, *, purpose: str) -> None:
    """Embed in a separate logical step; failures don't break the create flow."""
    try:
        await embed_owner(
            db,
            owner_type="messaging",
            owner_id=obj.id,
            text=_messaging_embed_text(obj),
            purpose=purpose,
        )
        await db.commit()
    except Exception as exc:
        log.warning(
            "messaging.embed_failed",
            messaging_id=str(obj.id),
            error=f"{type(exc).__name__}: {exc}",
        )
        await db.rollback()


async def list_messaging_documents(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    q: str | None = None,
    is_active: bool | None = None,
) -> Page[MessagingDocumentRead]:
    stmt = select(MessagingDocument).order_by(MessagingDocument.updated_at.desc())
    if q:
        stmt = stmt.where(MessagingDocument.title.ilike(f"%{q}%"))
    if is_active is not None:
        stmt = stmt.where(MessagingDocument.is_active.is_(is_active))

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[MessagingDocumentRead](
        items=[MessagingDocumentRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_messaging_document(
    db: AsyncSession, doc_id: UUID
) -> MessagingDocument:
    obj = await db.get(MessagingDocument, doc_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"messaging_document {doc_id} not found",
        )
    return obj


async def create_messaging_document(
    db: AsyncSession,
    payload: MessagingDocumentCreate,
    *,
    actor_label: str = "system",
) -> MessagingDocument:
    obj = MessagingDocument(**payload.model_dump())
    db.add(obj)
    await db.flush()  # populate obj.id without committing yet

    await write_audit(
        db,
        action="create",
        target_type="messaging_document",
        target_id=obj.id,
        before=None,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_safely(db, obj, purpose="embed:messaging:create")
    return obj


async def update_messaging_document(
    db: AsyncSession,
    doc_id: UUID,
    payload: MessagingDocumentUpdate,
    *,
    actor_label: str = "system",
) -> MessagingDocument:
    obj = await get_messaging_document(db, doc_id)
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
        target_type="messaging_document",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_safely(db, obj, purpose="embed:messaging:update")
    return obj


async def deactivate_messaging_document(
    db: AsyncSession,
    doc_id: UUID,
    *,
    actor_label: str = "system",
) -> None:
    """Soft-delete via is_active=false. Hard delete is intentionally not exposed."""
    obj = await get_messaging_document(db, doc_id)
    if not obj.is_active:
        return  # idempotent

    before = model_to_audit_dict(obj)
    obj.is_active = False
    await db.flush()
    await db.refresh(obj)  # see update_messaging_document

    await write_audit(
        db,
        action="deactivate",
        target_type="messaging_document",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
