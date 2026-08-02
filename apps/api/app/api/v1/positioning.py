"""Routes for messaging documents and strategic pillars.

WHAT THIS DOES
    CRUD for the positioning documents an operator uploads and for the
    strategic themes the org tracks.

HOW IT CONNECTS
    Calls       services/positioning.py, services/pdf.py
    Serves      /api/v1/messaging-documents*, /api/v1/pillars*

WORTH KNOWING
    One file because the matcher pools them into ONE signal: 'fit' is the
    conference text against messaging AND pillars together.

    Both defined the same four CRUD handler names; they now say which
    noun they operate on.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.db.session import DbSession
from app.schemas import (
    DOC_KIND_VALUES,
    MessagingDocumentCreate,
    MessagingDocumentRead,
    MessagingDocumentUpdate,
    MessagingDocUploadPreview,
    Page,
    PillarCreate,
    PillarRead,
    PillarUpdate,
    SmePillarLink,
    SmePillarRead,
)
from app.services import positioning, reports
from app.services.pdf import PdfRejected, validate_pdf_bytes

log = structlog.get_logger("scout.api.positioning")


# ==========================================================================
# messaging.py
# ==========================================================================


_r_messaging = APIRouter(prefix="/api/v1/messaging-documents", tags=["messaging"])


@_r_messaging.get("", response_model=Page[MessagingDocumentRead])
async def list_messaging_docs(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: str | None = None,
    is_active: bool | None = None,
    pillar_id: UUID | None = None,
) -> Page[MessagingDocumentRead]:
    return await positioning.list_messaging_documents(
        db, page=page, per_page=per_page, q=q, is_active=is_active, pillar_id=pillar_id
    )


@_r_messaging.get("/{doc_id}", response_model=MessagingDocumentRead)
async def get_messaging_doc(db: DbSession, doc_id: UUID) -> MessagingDocumentRead:
    obj = await positioning.get_messaging_document(db, doc_id)
    return MessagingDocumentRead.model_validate(obj)


@_r_messaging.post(
    "",
    response_model=MessagingDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_messaging_doc(
    db: DbSession,
    payload: MessagingDocumentCreate,
    actor_label: str = Query("system", description="Free-form attribution string."),
) -> MessagingDocumentRead:
    obj = await positioning.create_messaging_document(db, payload, actor_label=actor_label)
    return MessagingDocumentRead.model_validate(obj)


@_r_messaging.put("/{doc_id}", response_model=MessagingDocumentRead)
async def update_messaging_doc(
    db: DbSession,
    doc_id: UUID,
    payload: MessagingDocumentUpdate,
    actor_label: str = Query("system"),
) -> MessagingDocumentRead:
    obj = await positioning.update_messaging_document(db, doc_id, payload, actor_label=actor_label)
    return MessagingDocumentRead.model_validate(obj)


@_r_messaging.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_(
    db: DbSession,
    doc_id: UUID,
    actor_label: str = Query("system"),
) -> None:
    await positioning.deactivate_messaging_document(db, doc_id, actor_label=actor_label)


class MessagingUploadStarted(BaseModel):
    job_id: str


class MessagingUploadStatus(BaseModel):
    job_id: str
    status: str
    stage: str
    filename: str | None = None
    error: str | None = None
    extracted: MessagingDocUploadPreview | None = None


@_r_messaging.post(
    "/upload", response_model=MessagingUploadStarted, status_code=status.HTTP_202_ACCEPTED
)
async def upload_preview(
    db: DbSession,
    file: UploadFile,
    doc_kind: str = Query("other", description=f"One of: {', '.join(DOC_KIND_VALUES)}"),
) -> dict:
    """Accept a PDF and start extraction as a tracked background job.

    Same architecture as /talks/upload, for the same reasons: a real GTM
    PDF took 176s in-request (dead air, operator walked away, extraction
    discarded) and a heavier one OOMKilled the API pod. The job runs on
    the scheduler pod; poll GET /messaging-documents/upload/{job_id}.
    Nothing persists until the operator reviews and saves.
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

    from pathlib import Path
    from uuid import uuid4

    from app.db.models import IngestJob
    from app.scheduler import enqueue_now
    from app.settings import get_settings
    from app.tasks import messaging_upload_extract_task

    job_id = uuid4()
    updir = Path(get_settings().storage_path) / "messaging_uploads"
    updir.mkdir(parents=True, exist_ok=True)
    dest = updir / f"{job_id}.pdf"
    dest.write_bytes(raw)

    db.add(
        IngestJob(
            id=job_id,
            kind="messaging_upload",
            status="queued",
            stats={"stage": "queued", "filename": file.filename or "", "doc_kind": doc_kind},
        )
    )
    await db.commit()
    try:
        enqueue_now(
            messaging_upload_extract_task,
            job_id=f"messaging-upload-{job_id}",
            kwargs={
                "job_id": str(job_id),
                "file_path": str(dest),
                "filename": (file.filename or "").lower(),
                "doc_kind": doc_kind,
            },
        )
    except Exception as exc:
        # Committed-queued row + failed enqueue = eternal spinner. Mark it
        # failed now and surface the problem.
        row = await db.get(IngestJob, job_id)
        if row is not None:
            row.status = "failed"
            row.stats = {**(row.stats or {}), "stage": "failed"}
            row.error_text = f"enqueue failed: {type(exc).__name__}: {exc}"
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue the extraction job — try again shortly.",
        ) from exc
    return {"job_id": str(job_id)}


@_r_messaging.get("/upload/{job_id}", response_model=MessagingUploadStatus)
async def upload_status(db: DbSession, job_id: UUID) -> dict:
    from app.db.models import IngestJob

    row = await db.get(IngestJob, job_id)
    if row is None or row.kind != "messaging_upload":
        raise HTTPException(status_code=404, detail="upload job not found")
    stats = row.stats or {}
    return {
        "job_id": str(job_id),
        "status": row.status,
        "stage": stats.get("stage", row.status),
        "filename": stats.get("filename"),
        "error": (row.error_text or "").split("\n")[0] or None
        if row.status == "failed"
        else None,
        "extracted": stats.get("extracted"),
    }


# ==========================================================================
# pillars.py
# ==========================================================================


_r_pillars = APIRouter(prefix="/api/v1/pillars", tags=["pillars"])


@_r_pillars.get("", response_model=list[PillarRead])
async def list_pillars(db: DbSession) -> list[PillarRead]:
    return await positioning.list_pillars(db)


@_r_pillars.post("", response_model=PillarRead, status_code=status.HTTP_201_CREATED)
async def create_pillar(db: DbSession, payload: PillarCreate) -> PillarRead:
    return await positioning.create_pillar(db, payload)


@_r_pillars.get("/{pillar_id}", response_model=PillarRead)
async def get_pillar(db: DbSession, pillar_id: UUID) -> PillarRead:
    return await positioning.get_pillar(db, pillar_id)


@_r_pillars.put("/{pillar_id}", response_model=PillarRead)
async def update_pillar(db: DbSession, pillar_id: UUID, payload: PillarUpdate) -> PillarRead:
    return await positioning.update_pillar(db, pillar_id, payload)


@_r_pillars.delete("/{pillar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_(db: DbSession, pillar_id: UUID) -> None:
    await positioning.delete_pillar(db, pillar_id)


@_r_pillars.post(
    "/{pillar_id}/smes/{sme_id}",
    response_model=SmePillarRead,
    status_code=status.HTTP_201_CREATED,
)
async def link_sme(
    db: DbSession, pillar_id: UUID, sme_id: UUID, payload: SmePillarLink
) -> SmePillarRead:
    return await positioning.link_sme(db, pillar_id, sme_id, payload)


@_r_pillars.delete("/{pillar_id}/smes/{sme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_sme(db: DbSession, pillar_id: UUID, sme_id: UUID) -> None:
    await positioning.unlink_sme(db, pillar_id, sme_id)


@_r_pillars.get("/{pillar_id}/smes", response_model=list[SmePillarRead])
async def list_smes(db: DbSession, pillar_id: UUID) -> list[SmePillarRead]:
    return await positioning.list_pillar_smes(db, pillar_id)


class PillarConferenceItem(BaseModel):
    """One conference ranked against a pillar.

    ``pillar_score`` is this pillar's own alignment edge (conference_pillars,
    written by the matcher), NOT the conference's top-pillar assignment — so
    each pillar page gets its own ordering of the same corpus.
    ``overall_score`` is the live blend, identical to what the conference
    list and detail pages show.
    """

    id: str
    name: str
    slug: str
    status: str
    event_kind: str
    pillar_score: float
    overall_score: float | None = None
    start_date: date | None = None
    cfp_close_at: date | None = None


class PillarOutcomeRow(BaseModel):
    conference_id: str
    conference_name: str
    start_date: str | None = None
    n_people: int
    spend_usd: int | None = None
    leads_generated: int | None = None
    attendance_verdict: str | None = None


class PillarAnalytics(BaseModel):
    """Pillar performance from participation + outcome data.

    A conference aligned to two pillars counts toward both — these are
    per-pillar views, so sums must never be totalled across pillars.
    """

    pillar_id: str
    conferences_aligned: int
    conferences_attended: int
    conferences_planned: int
    participants_total: int
    spend_usd_total: int
    leads_total: int
    cost_per_lead_usd: float | None = None
    verdicts: dict[str, int]
    attended: list[PillarOutcomeRow]


@_r_pillars.get("/{pillar_id}/analytics", response_model=PillarAnalytics)
async def pillar_analytics_(db: DbSession, pillar_id: UUID) -> dict:
    """How this pillar is performing — computed server-side."""
    await positioning.get_pillar(db, pillar_id)  # 404 if unknown
    return await reports.pillar_analytics(db, pillar_id)


@_r_pillars.get("/{pillar_id}/conferences", response_model=list[PillarConferenceItem])
async def list_conferences(
    db: DbSession,
    pillar_id: UUID,
    limit: int = Query(default=15, ge=1, le=100),
) -> list[dict]:
    """Conferences ranked by how well they fit THIS pillar, best first."""
    return await positioning.list_pillar_conferences(db, pillar_id, limit=limit)


@_r_pillars.get("/{pillar_id}/talks")
async def list_talks(db: DbSession, pillar_id: UUID) -> list[dict]:
    return await positioning.list_pillar_talks(db, pillar_id)


@_r_pillars.get("/{pillar_id}/audiences")
async def list_audiences(db: DbSession, pillar_id: UUID) -> list[dict]:
    return await positioning.list_pillar_audiences(db, pillar_id)


router = APIRouter()
router.include_router(_r_messaging)
router.include_router(_r_pillars)
