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
from pydantic import BaseModel

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
from app.services.pdf import parse_and_chunk
from app.services.people import (
    TalkUploadPreview,
    extract_talk_from_text,
)

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


@_r_talks.post("/upload", response_model=TalkUploadPreview, status_code=status.HTTP_200_OK)
async def upload_(db: DbSession, file: UploadFile) -> TalkUploadPreview:
    """Parse an uploaded document and return an ExtractedTalk preview.

    Accepts PDF, TXT, and DOCX. Does NOT persist anything — the caller
    reviews the extracted fields and confirms via POST /talks to save.
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

    if ext == ".txt":
        try:
            full_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not decode text file: {exc}",
            ) from exc
    else:
        # PDF or DOCX: run Docling in a thread pool
        import tempfile
        from pathlib import Path

        from fastapi.concurrency import run_in_threadpool


        suffix = ext
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = Path(tmp.name)

        try:
            parsed = await run_in_threadpool(parse_and_chunk, tmp_path)
            full_text = parsed.full_text
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not parse document: {exc}",
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    extracted = await extract_talk_from_text(db=db, full_text=full_text)
    # Nothing talk-shaped persists here, but the LLM client stages its
    # spend row on this session — without the commit every upload's
    # llm_calls row rolled back and the cost ledger was blind to the
    # heaviest endpoint in the app. Same bug the messaging upload had.
    await db.commit()
    return TalkUploadPreview(extracted=extracted)


router = APIRouter()
router.include_router(_r_smes)
router.include_router(_r_talks)
