"""/api/v1/uploads — PDF upload + Docling-driven ingest.

Single endpoint for now: POST /api/v1/uploads/pdf. Multipart upload with
`file` + form fields `owner_type`, `owner_id`, `purpose`.

The flow runs synchronously inside the request (Docling parse + LLM embed).
For typical PDFs this completes in seconds; very large PDFs may take longer
and plan 13 (background jobs) will move long-running ingests to a queue.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.db.session import DbSession
from app.services.pdf import process_pdf_upload
from app.services.pdf.pipeline import PdfPipelineError, SUPPORTED_OWNER_TYPES
from app.services.pdf.storage import PdfRejected

log = structlog.get_logger("scout.api.uploads")
router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


@router.post("/pdf", status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    db: DbSession,
    file: Annotated[UploadFile, File(description="The PDF to ingest.")],
    owner_type: Annotated[
        str,
        Form(
            description=f"One of {', '.join(SUPPORTED_OWNER_TYPES)}",
        ),
    ],
    owner_id: Annotated[UUID, Form(description="The existing entity to attach to.")],
    purpose: Annotated[
        str,
        Form(description="messaging / audience / sme_bio / past_conference"),
    ],
) -> dict:
    """Upload a PDF, parse it with Docling, embed it, attach to the owner entity.

    Returns ``{ingest_job_id, owner_type, owner_id, file_path, sha256,
    page_count, chunks_inserted, status}``.

    Validation failures (size, wrong MIME, unknown owner_type) return 422.
    Processing failures (Docling crash, LLM error, owner not found) return 500
    with the ingest_jobs.id in the message for follow-up.
    """
    content = await file.read()
    log.info(
        "pdf.upload.received",
        owner_type=owner_type,
        owner_id=str(owner_id),
        purpose=purpose,
        filename=file.filename,
        bytes=len(content),
    )

    try:
        result = await process_pdf_upload(
            db,
            owner_type=owner_type,
            owner_id=owner_id,
            file_bytes=content,
            original_filename=file.filename or "uploaded.pdf",
            purpose=purpose,  # type: ignore[arg-type]
        )
    except PdfRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except PdfPipelineError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return result
