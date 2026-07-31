"""Routes for our speakers and their talks.

WHAT THIS DOES
    CRUD for SMEs and for the talks library, including the upload that
    parses an abstract or deck into a talk.

HOW IT CONNECTS
    Calls       services/people.py, services/pdf.py, services/records.py
    Serves      /api/v1/smes*, /api/v1/talks*

WORTH KNOWING
    One file because the matcher treats these as ONE signal — a conference
    is scored against SME bios AND the talks those people can give.

    Both modules defined ``list_``, ``get_``, ``create_`` and ``update_``.
    Merged, the second set shadowed the first, so they now say which noun
    they operate on.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict

from app.db.session import DbSession
from app.schemas import (
    Page,
    ReuseCheckResult,
    SmeCreate,
    SmeRead,
    SmeUpdate,
    TalkCreate,
    TalkRead,
    TalkSubmissionCreate,
    TalkSubmissionRead,
    TalkSubmissionUpdate,
    TalkUpdate,
)
from app.services import people, reports

log = structlog.get_logger("scout.api.people")


# ==========================================================================
# smes.py
# ==========================================================================


_r_smes = APIRouter(prefix="/api/v1/smes", tags=["smes"])


@_r_smes.get("", response_model=Page[SmeRead])
async def list_smes(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: str | None = None,
    team: str | None = None,
    external_only: bool | None = Query(
        default=None,
        description=(
            "True returns everyone NOT on the primary team. Filtering this "
            "in the client filters only the page it already has."
        ),
    ),
    is_active: bool | None = None,
) -> Page[SmeRead]:
    return await people.list_smes(
        db, page=page, per_page=per_page, q=q, team=team, is_active=is_active
    )


@_r_smes.get("/{sme_id}", response_model=SmeRead)
async def get_sme(db: DbSession, sme_id: UUID) -> SmeRead:
    obj = await people.get_sme(db, sme_id)
    return await people.to_read(db, obj)


class SmeEventRow(BaseModel):
    conference_id: str
    conference_name: str
    start_date: str | None = None
    activity: str
    attended: bool
    #: Event-level outcome fields — the conference's numbers, shown in the
    #: context of this person's participation, NOT a personal P&L.
    spend_usd: int | None = None
    leads_generated: int | None = None
    attendance_verdict: str | None = None


class SmeAnalytics(BaseModel):
    sme_id: str
    events_total: int
    events_attended: int
    events_upcoming: int
    by_activity: dict[str, int]
    attended_events_spend_usd: int
    attended_events_leads: int
    verdicts: dict[str, int]
    events: list[SmeEventRow]


@_r_smes.get("/{sme_id}/analytics", response_model=SmeAnalytics)
async def sme_analytics_(db: DbSession, sme_id: UUID) -> dict:
    """How this person is doing on the circuit — computed server-side
    from participation rows + conference outcome fields."""
    await people.get_sme(db, sme_id)  # 404 if unknown
    return await reports.sme_analytics(db, sme_id)


@_r_smes.post("", response_model=SmeRead, status_code=status.HTTP_201_CREATED)
async def create_sme(
    db: DbSession,
    payload: SmeCreate,
    actor_label: str = Query("system"),
) -> SmeRead:
    obj = await people.create_sme(db, payload, actor_label=actor_label)
    return await people.to_read(db, obj)


@_r_smes.put("/{sme_id}", response_model=SmeRead)
async def update_sme(
    db: DbSession,
    sme_id: UUID,
    payload: SmeUpdate,
    actor_label: str = Query("system"),
) -> SmeRead:
    obj = await people.update_sme(db, sme_id, payload, actor_label=actor_label)
    return await people.to_read(db, obj)


@_r_smes.delete("/{sme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_(
    db: DbSession,
    sme_id: UUID,
    actor_label: str = Query("system"),
) -> None:
    await people.deactivate_sme(db, sme_id, actor_label=actor_label)


# ==========================================================================
# talks.py
# ==========================================================================


_r_talks = APIRouter(prefix="/api/v1/talks", tags=["talks"])


_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx"}


_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB


@_r_talks.get("", response_model=Page[TalkRead])
async def list_talks(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    pillar_id: UUID | None = None,
    sme_id: UUID | None = None,
    review_status: str | None = None,
    is_active: bool | None = True,
) -> Page[TalkRead]:
    return await people.list_talks(
        db,
        page=page,
        per_page=per_page,
        pillar_id=pillar_id,
        sme_id=sme_id,
        review_status=review_status,
        is_active=is_active,
    )


@_r_talks.post("", response_model=TalkRead, status_code=status.HTTP_201_CREATED)
async def create_talk(db: DbSession, payload: TalkCreate) -> TalkRead:
    return await people.create_talk(db, payload)


@_r_talks.get("/{talk_id}", response_model=TalkRead)
async def get_talk(db: DbSession, talk_id: UUID) -> TalkRead:
    return await people.get_talk(db, talk_id)


@_r_talks.put("/{talk_id}", response_model=TalkRead)
async def update_talk(db: DbSession, talk_id: UUID, payload: TalkUpdate) -> TalkRead:
    return await people.update_talk(db, talk_id, payload)


@_r_talks.delete("/{talk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_(db: DbSession, talk_id: UUID) -> None:
    await people.soft_delete_talk(db, talk_id)


@_r_talks.post(
    "/{talk_id}/submit",
    response_model=TalkSubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_(db: DbSession, talk_id: UUID, payload: TalkSubmissionCreate) -> TalkSubmissionRead:
    return await people.create_submission(db, talk_id, payload)


@_r_talks.patch("/{talk_id}/submissions/{sub_id}", response_model=TalkSubmissionRead)
async def update_submission_(
    db: DbSession, talk_id: UUID, sub_id: UUID, payload: TalkSubmissionUpdate
) -> TalkSubmissionRead:
    return await people.update_submission(db, talk_id, sub_id, payload)


@_r_talks.delete("/{talk_id}/submissions/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission_(db: DbSession, talk_id: UUID, sub_id: UUID) -> None:
    await people.delete_submission(db, talk_id, sub_id)


@_r_talks.get("/{talk_id}/reuse-check", response_model=ReuseCheckResult)
async def reuse_check_(db: DbSession, talk_id: UUID) -> ReuseCheckResult:
    return await people.reuse_check(db, talk_id)


class TalkUploadStarted(BaseModel):
    job_id: str


class TalkUploadPreviewBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    abstract: str
    key_themes: list[str] = []
    suggested_pillar_name: str | None = None
    target_audience_description: str | None = None
    suggested_duration_minutes: int | None = None
    talk_format: str | None = None


class TalkUploadStatus(BaseModel):
    job_id: str
    #: queued | running | complete | failed
    status: str
    #: queued | parsing | extracting | done | failed
    stage: str
    filename: str | None = None
    error: str | None = None
    extracted: TalkUploadPreviewBody | None = None


@_r_talks.post("/upload", response_model=TalkUploadStarted, status_code=status.HTTP_202_ACCEPTED)
async def upload_(db: DbSession, file: UploadFile) -> dict:
    """Accept a document and start extraction as a tracked background job.

    Docling + the LLM take ~a minute for a real PDF. Running that inside
    the request meant a blind wait and a fight with every proxy timeout
    between browser and worker; as a job the UI polls real stages and a
    mid-run refresh loses nothing. Poll GET /talks/upload/{job_id}.
    """
    filename = (file.filename or "").lower()
    ext = next((e for e in _SUPPORTED_EXTENSIONS if filename.endswith(e)), None)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported file type '{filename}'. "
                f"Accepted: {sorted(_SUPPORTED_EXTENSIONS)}"
            ),
        )
    raw_bytes = await file.read()
    if len(raw_bytes) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File too large ({len(raw_bytes)} bytes); max is {_MAX_FILE_BYTES}.",
        )

    # Shared storage, not /tmp: in production the job executes on the
    # scheduler pod, which sees the same RWX volume but not this pod's tmp.
    from pathlib import Path
    from uuid import uuid4

    from app.db.models import IngestJob
    from app.scheduler import enqueue_now
    from app.settings import get_settings
    from app.tasks import talk_upload_extract_task

    job_id = uuid4()
    updir = Path(get_settings().storage_path) / "talk_uploads"
    updir.mkdir(parents=True, exist_ok=True)
    dest = updir / f"{job_id}{ext}"
    dest.write_bytes(raw_bytes)

    db.add(
        IngestJob(
            id=job_id,
            kind="talk_upload",
            status="queued",
            stats={"stage": "queued", "filename": file.filename or ""},
        )
    )
    await db.commit()
    enqueue_now(
        talk_upload_extract_task,
        job_id=f"talk-upload-{job_id}",
        kwargs={
            "job_id": str(job_id),
            "file_path": str(dest),
            "filename": filename,
        },
    )
    return {"job_id": str(job_id)}


@_r_talks.get("/upload/{job_id}", response_model=TalkUploadStatus)
async def upload_status(db: DbSession, job_id: UUID) -> dict:
    from app.db.models import IngestJob

    row = await db.get(IngestJob, job_id)
    if row is None or row.kind != "talk_upload":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="upload job not found"
        )
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


router = APIRouter()
router.include_router(_r_smes)
router.include_router(_r_talks)
