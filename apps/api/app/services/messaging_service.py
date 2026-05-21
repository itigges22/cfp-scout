"""Messaging-documents service.

Plan 09 surface: list / get / create / update / soft-delete.

Embedding regeneration is enqueued on create/update once the embedder lands
(plan 11). For now the service writes the row + audits; plan 11 hooks the
``embed_owner`` task into the same paths.
"""

from __future__ import annotations

from uuid import UUID

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
