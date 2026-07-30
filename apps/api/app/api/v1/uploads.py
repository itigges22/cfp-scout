"""POST /api/v1/uploads/pdf — attach a PDF to an existing record and index it.

WHAT THIS DOES
    Takes a multipart upload (``file`` plus form fields ``owner_type``,
    ``owner_id``, ``purpose``), parses the PDF with Docling, splits the text
    into chunks, embeds them, and stores them against the owning entity.
    Returns the ingest job id, file path, sha256, page count and chunk
    count. Validation problems (size, wrong MIME type, unknown owner_type)
    give 422; processing failures give 500 with the ingest_jobs id in the
    message.

HOW IT CONNECTS
    Called by   main.py (registered as a router). No code in apps/web/src
                posts here — the UI uses the per-resource upload endpoints
                (/messaging-documents/upload, /talks/upload) instead.
    Writes      vectors.document_chunks and app.ingest_jobs; the PDF file
                itself lands on disk
    Helpers     services/pdf/ (pipeline, parser, storage)

WORTH KNOWING
    Parsing and embedding both run inside the request, so a large PDF holds
    the HTTP connection open for the whole job.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.db.session import DbSession
from app.services.pdf import (
    SUPPORTED_OWNER_TYPES,
    PdfPipelineError,
    PdfRejected,
    process_pdf_upload,
)

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
        Form(description="messaging / audience / sme_bio"),
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
