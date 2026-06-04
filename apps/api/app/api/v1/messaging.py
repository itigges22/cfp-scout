"""/api/v1/messaging-documents routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.db.session import DbSession
from app.schemas.common import Page
from app.schemas.messaging import (
    DOC_KIND_VALUES,
    MessagingDocUploadPreview,
    MessagingDocumentCreate,
    MessagingDocumentRead,
    MessagingDocumentUpdate,
)
from app.services import messaging_service
from app.services.messaging_extraction import extract_messaging_from_text
from app.services.pdf.parser import parse_and_chunk
from app.services.pdf.storage import PdfRejected, save_pdf, validate_pdf_bytes

router = APIRouter(prefix="/api/v1/messaging-documents", tags=["messaging"])


@router.get("", response_model=Page[MessagingDocumentRead])
async def list_(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: str | None = None,
    is_active: bool | None = None,
    pillar_id: UUID | None = None,
) -> Page[MessagingDocumentRead]:
    return await messaging_service.list_messaging_documents(
        db, page=page, per_page=per_page, q=q, is_active=is_active, pillar_id=pillar_id
    )


@router.get("/{doc_id}", response_model=MessagingDocumentRead)
async def get_(db: DbSession, doc_id: UUID) -> MessagingDocumentRead:
    obj = await messaging_service.get_messaging_document(db, doc_id)
    return MessagingDocumentRead.model_validate(obj)


@router.post(
    "",
    response_model=MessagingDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_(
    db: DbSession,
    payload: MessagingDocumentCreate,
    actor_label: str = Query("system", description="Free-form attribution string."),
) -> MessagingDocumentRead:
    obj = await messaging_service.create_messaging_document(db, payload, actor_label=actor_label)
    return MessagingDocumentRead.model_validate(obj)


@router.put("/{doc_id}", response_model=MessagingDocumentRead)
async def update_(
    db: DbSession,
    doc_id: UUID,
    payload: MessagingDocumentUpdate,
    actor_label: str = Query("system"),
) -> MessagingDocumentRead:
    obj = await messaging_service.update_messaging_document(
        db, doc_id, payload, actor_label=actor_label
    )
    return MessagingDocumentRead.model_validate(obj)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_(
    db: DbSession,
    doc_id: UUID,
    actor_label: str = Query("system"),
) -> None:
    await messaging_service.deactivate_messaging_document(db, doc_id, actor_label=actor_label)


@router.post("/upload", response_model=MessagingDocUploadPreview)
async def upload_preview(
    db: DbSession,
    file: UploadFile,
    doc_kind: str = Query("other", description=f"One of: {', '.join(DOC_KIND_VALUES)}"),
) -> MessagingDocUploadPreview:
    """Parse a PDF and extract messaging fields via LLM.

    Returns a preview for operator review — does NOT persist to the database.
    After reviewing/editing, POST to /api/v1/messaging-documents to save.
    """
    if doc_kind not in DOC_KIND_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"doc_kind must be one of: {', '.join(DOC_KIND_VALUES)}",
        )

    raw = await file.read()
    try:
        validate_pdf_bytes(raw)
    except PdfRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    on_disk, _ = save_pdf(raw)
    parsed = await run_in_threadpool(parse_and_chunk, on_disk)

    return await extract_messaging_from_text(
        db=db,
        full_text=parsed.full_text,
        doc_kind=doc_kind,
    )
