"""/api/v1/talks — talks library CRUD + submissions + reuse checks."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, UploadFile, status

from app.db.session import DbSession
from app.schemas.common import Page
from app.schemas.talk import (
    ReuseCheckResult,
    TalkCreate,
    TalkRead,
    TalkSubmissionCreate,
    TalkSubmissionRead,
    TalkSubmissionUpdate,
    TalkUpdate,
)
from app.services import talk_service
from app.services.talk_extraction import (
    TalkUploadPreview,
    extract_talk_from_text,
    fuzzy_match_topics,
)

router = APIRouter(prefix="/api/v1/talks", tags=["talks"])

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx"}
_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB


@router.get("", response_model=Page[TalkRead])
async def list_(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    pillar_id: UUID | None = None,
    tag_id: UUID | None = None,
    sme_id: UUID | None = None,
    review_status: str | None = None,
    is_active: bool | None = True,
) -> Page[TalkRead]:
    return await talk_service.list_talks(
        db,
        page=page,
        per_page=per_page,
        pillar_id=pillar_id,
        tag_id=tag_id,
        sme_id=sme_id,
        review_status=review_status,
        is_active=is_active,
    )


@router.post("", response_model=TalkRead, status_code=status.HTTP_201_CREATED)
async def create_(db: DbSession, payload: TalkCreate) -> TalkRead:
    return await talk_service.create_talk(db, payload)


@router.get("/{talk_id}", response_model=TalkRead)
async def get_(db: DbSession, talk_id: UUID) -> TalkRead:
    return await talk_service.get_talk(db, talk_id)


@router.put("/{talk_id}", response_model=TalkRead)
async def update_(db: DbSession, talk_id: UUID, payload: TalkUpdate) -> TalkRead:
    return await talk_service.update_talk(db, talk_id, payload)


@router.delete("/{talk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_(db: DbSession, talk_id: UUID) -> None:
    await talk_service.soft_delete_talk(db, talk_id)


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


@router.post(
    "/{talk_id}/submit",
    response_model=TalkSubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_(db: DbSession, talk_id: UUID, payload: TalkSubmissionCreate) -> TalkSubmissionRead:
    return await talk_service.create_submission(db, talk_id, payload)


@router.patch("/{talk_id}/submissions/{sub_id}", response_model=TalkSubmissionRead)
async def update_submission_(
    db: DbSession, talk_id: UUID, sub_id: UUID, payload: TalkSubmissionUpdate
) -> TalkSubmissionRead:
    return await talk_service.update_submission(db, talk_id, sub_id, payload)


@router.delete("/{talk_id}/submissions/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission_(db: DbSession, talk_id: UUID, sub_id: UUID) -> None:
    await talk_service.delete_submission(db, talk_id, sub_id)


# ---------------------------------------------------------------------------
# Reuse check
# ---------------------------------------------------------------------------


@router.get("/{talk_id}/reuse-check", response_model=ReuseCheckResult)
async def reuse_check_(db: DbSession, talk_id: UUID) -> ReuseCheckResult:
    return await talk_service.reuse_check(db, talk_id)


# ---------------------------------------------------------------------------
# Upload + preview (no DB write)
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=TalkUploadPreview, status_code=status.HTTP_200_OK)
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

        from app.services.pdf.parser import parse_and_chunk

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
    topic_matches = await fuzzy_match_topics(
        db=db, raw_topics=extracted.suggested_topics
    )
    return TalkUploadPreview(extracted=extracted, suggested_topic_matches=topic_matches)
