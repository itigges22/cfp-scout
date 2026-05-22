"""Top-level PDF upload pipeline.

Orchestrates the steps an uploaded PDF goes through:

  1. Validate bytes (size, magic) — fast pre-write check.
  2. Save to STORAGE_PATH/pdf_uploads/<uuid>.pdf on the named volume.
  3. Record an `ingest_jobs` row in the `received` state.
  4. Parse + chunk with Docling (off the event loop via run_in_threadpool).
  5. For supported owner types: update the owner row's file_path + raw_content.
  6. Insert chunks via the embed pipeline (one LLM batch call).
  7. Mark the ingest_job complete with the result stats.

Failures at any stage mark the job `failed` with a traceback in `error_text`.
The PDF on disk is left in place (so the user can retry without re-uploading).
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import structlog
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import MessagingDocument
from app.db.models.ops import IngestJob
from app.services.embeddings.pipeline import embed_owner
from app.services.pdf.parser import ParsedPdf, parse_and_chunk
from app.services.pdf.storage import PdfRejected, save_pdf, validate_pdf_bytes

log = structlog.get_logger("scout.pdf.pipeline")

# Owner types that accept PDF attachments. Same enum the embeddings layer uses.
SUPPORTED_OWNER_TYPES: tuple[str, ...] = ("messaging", "audience", "sme_bio", "past_conference")


class PdfPipelineError(Exception):
    """Anything that's not a per-row validation failure surfaces as this."""


async def process_pdf_upload(
    db: AsyncSession,
    *,
    owner_type: str,
    owner_id: UUID,
    file_bytes: bytes,
    original_filename: str,
    purpose: Literal["messaging", "audience", "sme_bio", "past_conference"],
) -> dict[str, Any]:
    """Run the full upload flow. Returns a JSON-serialisable summary.

    Raises PdfRejected for pre-write validation issues so the api layer can
    return 422; other failures bubble as PdfPipelineError (mapped to 500).
    """
    if owner_type not in SUPPORTED_OWNER_TYPES:
        raise PdfRejected(
            f"owner_type {owner_type!r} not supported; valid: {sorted(SUPPORTED_OWNER_TYPES)}"
        )

    # 1. Pre-write validation (cheap; reject before disk + DB)
    validate_pdf_bytes(file_bytes)

    # 2. Persist to volume
    on_disk, sha = save_pdf(file_bytes)
    file_path_rel = str(on_disk.relative_to(Path(on_disk).parents[2]))  # e.g. storage/pdf_uploads/<uuid>.pdf

    # 3. ingest_jobs row, status=received
    job = IngestJob(
        kind="pdf_upload",
        status="received",
        started_at=datetime.now(tz=timezone.utc),
        stats={
            "owner_type": owner_type,
            "owner_id": str(owner_id),
            "purpose": purpose,
            "original_filename": original_filename,
            "bytes": len(file_bytes),
            "sha256": sha,
            "file_path": file_path_rel,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    try:
        # 4. Docling parse + chunk — synchronous, off the event loop.
        parsed: ParsedPdf = await _update_job_phase(
            db, job, "parsing", lambda: run_in_threadpool(parse_and_chunk, on_disk)
        )

        # 5. Owner-side update. Only `messaging_documents` has file_path +
        #    raw_content fields today; other owner types just embed.
        if owner_type == "messaging":
            await _attach_to_messaging_doc(
                db, owner_id, file_path=str(on_disk), raw_content=parsed.full_text
            )

        # 6. Embed via the existing pipeline. Docling's chunks already carry
        #    structural metadata; we forward it via extra_metadata.
        #    We pass each chunk's text individually to preserve metadata.
        chunks_inserted = await _embed_docling_chunks(
            db,
            owner_type=owner_type,
            owner_id=owner_id,
            parsed=parsed,
        )

        # 7. Mark complete.
        job.status = "complete"
        job.finished_at = datetime.now(tz=timezone.utc)
        job.stats = {
            **(job.stats or {}),
            "page_count": parsed.page_count,
            "chunks_inserted": chunks_inserted,
            "markdown_chars": len(parsed.full_text),
        }
        await db.commit()

        return {
            "ingest_job_id": str(job.id),
            "owner_type": owner_type,
            "owner_id": str(owner_id),
            "file_path": str(on_disk),
            "sha256": sha,
            "page_count": parsed.page_count,
            "chunks_inserted": chunks_inserted,
            "status": "complete",
        }
    except Exception as exc:
        # Mark the job failed (separately committed) and re-raise.
        job.status = "failed"
        job.finished_at = datetime.now(tz=timezone.utc)
        job.error_text = (
            f"{type(exc).__name__}: {exc}\n" + traceback.format_exc()
        )[:8000]
        await db.commit()
        log.error(
            "pdf.upload.failed",
            ingest_job_id=str(job.id),
            owner_type=owner_type,
            owner_id=str(owner_id),
            error_type=type(exc).__name__,
        )
        raise PdfPipelineError(f"PDF processing failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
async def _update_job_phase(
    db: AsyncSession,
    job: IngestJob,
    phase: str,
    coro_factory,
) -> Any:
    """Update job.status to `phase`, run the coroutine, return its result.

    Phase names appear in the ingest_jobs.status column; the api's
    /diagnostics page (plan 26) will surface them.
    """
    job.status = phase
    await db.commit()
    t0 = time.perf_counter()
    result = await coro_factory()
    dur_ms = int((time.perf_counter() - t0) * 1000)
    log.info("pdf.phase.done", phase=phase, duration_ms=dur_ms)
    return result


async def _attach_to_messaging_doc(
    db: AsyncSession,
    doc_id: UUID,
    *,
    file_path: str,
    raw_content: str,
) -> None:
    obj = await db.get(MessagingDocument, doc_id)
    if obj is None:
        raise PdfPipelineError(f"messaging_document {doc_id} not found")
    obj.file_path = file_path
    obj.raw_content = raw_content
    await db.commit()


async def _embed_docling_chunks(
    db: AsyncSession,
    *,
    owner_type: str,
    owner_id: UUID,
    parsed: ParsedPdf,
) -> int:
    """Persist Docling-chunked content with structural metadata.

    We can't just call ``embed_owner(text=...)`` because that re-chunks via
    the plain-text chunker, throwing away Docling's structural splits. So we
    bypass the plain-text chunker by joining the chunks back into one synthetic
    text **for the LLM batch call**, then write one DocumentChunk row per
    Docling chunk with the metadata preserved.

    Idempotent: deletes prior chunks for the (owner, active model) first.
    """
    from sqlalchemy import delete

    from app.db.models.vectors import DocumentChunk
    from app.services.embeddings.pipeline import get_active_embedding_model
    from app.services.llm import EmbeddingRequest, get_llm_client

    model_row = await get_active_embedding_model(db)

    # Drop prior chunks for this owner under the active model.
    await db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.owner_type == owner_type,
            DocumentChunk.owner_id == owner_id,
            DocumentChunk.embedding_model_id == model_row.id,
        )
    )

    if not parsed.chunks:
        await db.commit()
        return 0

    response = await get_llm_client().embed(
        EmbeddingRequest(
            texts=[c.text for c in parsed.chunks],
            purpose=f"embed:{owner_type}:pdf",
        ),
        db=db,
    )
    if len(response.vectors) != len(parsed.chunks):
        raise PdfPipelineError(
            f"embedder returned {len(response.vectors)} vectors for {len(parsed.chunks)} chunks"
        )

    for chunk, vec in zip(parsed.chunks, response.vectors, strict=True):
        db.add(
            DocumentChunk(
                owner_type=owner_type,
                owner_id=owner_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                embedding_model_id=model_row.id,
                embedding=vec,
                chunk_metadata=chunk.metadata,
            )
        )

    await db.commit()
    return len(parsed.chunks)
