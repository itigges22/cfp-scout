"""PDF ingestion, end to end: validate, store, parse, chunk, embed.

WHAT THIS DOES
    An uploaded PDF is checked for a real PDF magic number and a size
    limit, written to the storage volume under a content hash, parsed into
    text and chunks by Docling, embedded, and tracked by an ingest job row
    the UI polls.

    Parsing walks a tier ladder — small, medium, large — and retries a
    lighter tier whenever the heavier one dies. Docling is run in a
    throwaway subprocess (services/pdf_worker.py) because its models can
    push memory far enough that the kernel's OOM killer steps in, and that
    must not take the API down with it.

HOW IT CONNECTS
    Called by   api/v1/uploads.py (the whole path), api/v1/messaging.py and
                api/v1/talks.py (validate + store + parse)
    Writes      the storage volume, ingest job rows, messaging_doc rows,
                embedding chunks
    Helpers     services/pdf_worker.py (the subprocess), embeddings

WORTH KNOWING
    This was four modules — storage, parser, pipeline and the worker — and
    apart from the worker each had exactly one internal caller and no life
    of its own. Reading the upload path meant three files to answer one
    question. The worker stays separate because it is a genuine process
    boundary: it is executed by path, not imported.

    Any non-zero worker exit, 137 included, simply means "try a lighter
    tier", so the worker must fail by exiting, never by printing partial
    JSON.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk, IngestJob, MessagingDocument
from app.services.embeddings import (
    OWNER_TYPES,
    ChunkData,
    get_active_embedding_model,
)
from app.services.llm import EmbeddingRequest, get_llm_client
from app.settings import get_settings

log = structlog.get_logger("scout.pdf")


# ==========================================================================
# storage.py
# ==========================================================================


PDF_MAGIC = b"%PDF-"


MAX_PDF_BYTES = 25 * 1024 * 1024  # 25MB


class PdfRejected(Exception):
    """Raised when an upload fails the pre-write checks."""


def validate_pdf_bytes(data: bytes) -> None:
    """Cheap pre-write validation. Raises PdfRejected with a clear message."""
    if not data:
        raise PdfRejected("file is empty")
    if len(data) > MAX_PDF_BYTES:
        raise PdfRejected(f"file too large: {len(data):,} bytes; max {MAX_PDF_BYTES:,}")
    if not data.startswith(PDF_MAGIC):
        raise PdfRejected("not a PDF (file does not start with '%PDF-' magic)")


def save_pdf(data: bytes) -> tuple[Path, str]:
    """Write `data` to a UUID-named file under STORAGE_PATH/pdf_uploads/.

    Returns:
        (absolute_path_on_disk, sha256_hex_of_contents)
    """
    settings = get_settings()
    root = Path(settings.storage_path) / "pdf_uploads"
    root.mkdir(parents=True, exist_ok=True)

    pdf_id = str(uuid4())
    target = root / f"{pdf_id}.pdf"
    target.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    log.info("pdf.saved", path=str(target), bytes=len(data), sha256=sha[:12])
    return target, sha


# ==========================================================================
# parser.py
# ==========================================================================


SMALL_THRESHOLD_BYTES = 4 * 1024 * 1024  # 4 MB


LARGE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB


PipelineTier = Literal["small", "medium", "large", "text_only"]


class PdfParseError(RuntimeError):
    """All pipeline tiers failed for this PDF."""


_TIER_TIMEOUT_SECONDS: dict[PipelineTier, int] = {
    # Sized for an api container that may be sharing 4 GiB with the model
    # weight cache. Docling makes steady progress but pages of layout
    # extraction take real wall-clock on CPU — bigger PDFs proportionally.
    "small": 600,
    "medium": 600,
    "large": 600,
    "text_only": 120,
}


_WORKER_PATH = str(Path(__file__).parent / "pdf_worker.py")


def pick_tier(size_bytes: int) -> PipelineTier:
    """Choose a Docling pipeline tier from file size."""
    if size_bytes < SMALL_THRESHOLD_BYTES:
        return "small"
    if size_bytes < LARGE_THRESHOLD_BYTES:
        return "medium"
    return "large"


@dataclass(slots=True)
class ParsedPdf:
    """What ``parse_and_chunk`` returns to the pipeline layer."""

    full_text: str
    chunks: list[ChunkData]
    page_count: int
    tier_used: PipelineTier


def parse_and_chunk(path: Path) -> ParsedPdf:
    """Parse `path` with Docling, chunk via HybridChunker.

    Tries the size-appropriate Docling tier first; on failure, walks
    DOWN the tiers (small → medium → large) so big-PDF runtime
    failures fall back to a cheaper pipeline rather than 500-ing the
    upload. Raises ``PdfParseError`` only when every tier has failed.

    Synchronous — wrap in run_in_threadpool from the route handler.
    """
    size_bytes = path.stat().st_size
    primary = pick_tier(size_bytes)
    # Cascade strictly from heaviest to lightest. `text_only` is the
    # absolute floor — runs via pypdfium2 with no model weights, so even
    # a memory-pinched VM can complete it.
    weight_order: list[PipelineTier] = ["small", "medium", "large", "text_only"]
    primary_idx = weight_order.index(primary)
    fallback_order: list[PipelineTier] = weight_order[primary_idx:]

    last_error: Exception | None = None
    for tier in fallback_order:
        try:
            if tier == "text_only":
                parsed = _parse_text_only(path)
            else:
                parsed = _parse_with_tier_subprocess(path, tier)
            if tier != primary:
                log.warning(
                    "docling.parse.degraded",
                    path=str(path),
                    size_bytes=size_bytes,
                    primary_tier=primary,
                    tier_used=tier,
                )
            return parsed
        except Exception as exc:
            log.warning(
                "docling.parse.tier_failed",
                path=str(path),
                tier=tier,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            last_error = exc
            continue

    raise PdfParseError(
        f"All Docling tiers failed for {path} (size={size_bytes} bytes)"
    ) from last_error


def _parse_with_tier_subprocess(path: Path, tier: PipelineTier) -> ParsedPdf:
    """Run the Docling tier in a child python process.

    Subprocess isolation matters: a SIGKILL from the kernel OOM killer
    (return code 137) takes out the worker only — the api stays up and
    we cascade to the next tier. Without this, an OOM during parse
    would take the whole api with it.
    """
    timeout = _TIER_TIMEOUT_SECONDS[tier]
    log.info("docling.subprocess.begin", path=str(path), tier=tier, timeout=timeout)

    try:
        # subprocess.run is fed a hardcoded path + a Literal-typed tier;
        # the only operator-supplied input is `path`, which has already
        # passed the upload-route's MIME/size/SSRF checks before reaching
        # the parser. No shell, no shell=True.
        result = subprocess.run(  # noqa: S603 — args are list[str]; path validated upstream
            [sys.executable, _WORKER_PATH, str(path), tier],
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"tier={tier} timed out after {timeout}s") from exc

    if result.returncode != 0:
        # Common returncodes: 137 = OOM kill, 139 = SIGSEGV, 1 = python exc.
        stderr_tail = (result.stderr or b"").decode("utf-8", errors="replace")[-400:]
        raise RuntimeError(f"tier={tier} worker exited {result.returncode}: {stderr_tail}")

    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        head = (result.stdout or b"")[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"tier={tier} worker returned non-JSON: {head!r}") from exc

    full_text = payload["full_text"]
    page_count = int(payload["page_count"])
    chunks: list[ChunkData] = [
        ChunkData(
            text=c["text"],
            chunk_index=c["chunk_index"],
            token_count=c["token_count"],
            metadata=c.get("metadata") or {},
        )
        for c in payload["chunks"]
    ]

    log.info(
        "docling.parse.done",
        path=str(path),
        tier=tier,
        pages=page_count,
        chunks=len(chunks),
        markdown_chars=len(full_text),
    )
    return ParsedPdf(
        full_text=full_text,
        chunks=chunks,
        page_count=page_count,
        tier_used=tier,
    )


def _parse_text_only(path: Path) -> ParsedPdf:
    """No-model fallback: extract page text via pypdfium2, chunk by page.

    Used when every Docling tier failed (typically because we ran out of
    memory loading the layout/table models). The chunks here are coarser
    — one per page — but the matcher's embedding stage still gets useful
    signal, and the agent's RAG retrieval still has something to surface.
    """
    import pypdfium2 as pdfium

    log.warning("docling.parse.text_only_fallback", path=str(path))

    pdf = pdfium.PdfDocument(str(path))
    try:
        page_count = len(pdf)
        page_texts: list[str] = []
        for i, page in enumerate(pdf):
            try:
                textpage = page.get_textpage()
                page_texts.append(textpage.get_text_range() or "")
                textpage.close()
            finally:
                page.close()
    finally:
        pdf.close()

    full_text = "\n\n".join(page_texts)
    chunks: list[ChunkData] = []
    for index, text in enumerate(page_texts):
        if not text.strip():
            continue
        chunks.append(
            ChunkData(
                text=text,
                chunk_index=index,
                token_count=max(1, len(text) // 4),
                metadata={"page_number": index + 1, "content_type": "text"},
            )
        )

    log.info(
        "docling.parse.done",
        path=str(path),
        tier="text_only",
        pages=page_count,
        chunks=len(chunks),
        markdown_chars=len(full_text),
    )
    return ParsedPdf(
        full_text=full_text,
        chunks=chunks,
        page_count=page_count,
        tier_used="text_only",
    )


# ==========================================================================
# pipeline.py
# ==========================================================================


SUPPORTED_OWNER_TYPES: tuple[str, ...] = ("messaging", "audience", "sme_bio")


assert set(SUPPORTED_OWNER_TYPES) <= set(OWNER_TYPES), (
    "PDF owner types must be a subset of the canonical chunk owner types"
)


class PdfPipelineError(Exception):
    """Anything that's not a per-row validation failure surfaces as this."""


async def process_pdf_upload(
    db: AsyncSession,
    *,
    owner_type: str,
    owner_id: UUID,
    file_bytes: bytes,
    original_filename: str,
    purpose: Literal["messaging", "audience", "sme_bio"],
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
    file_path_rel = str(
        on_disk.relative_to(Path(on_disk).parents[2])
    )  # e.g. storage/pdf_uploads/<uuid>.pdf

    # 3. ingest_jobs row, status=received
    job = IngestJob(
        kind="pdf_upload",
        status="received",
        started_at=datetime.now(tz=UTC),
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
        job.finished_at = datetime.now(tz=UTC)
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
        job.finished_at = datetime.now(tz=UTC)
        job.error_text = (f"{type(exc).__name__}: {exc}\n" + traceback.format_exc())[:8000]
        await db.commit()
        log.error(
            "pdf.upload.failed",
            ingest_job_id=str(job.id),
            owner_type=owner_type,
            owner_id=str(owner_id),
            error_type=type(exc).__name__,
        )
        raise PdfPipelineError(f"PDF processing failed: {exc}") from exc


async def _update_job_phase(
    db: AsyncSession,
    job: IngestJob,
    phase: str,
    coro_factory,
) -> Any:
    """Update job.status to `phase`, run the coroutine, return its result.

    Phase names appear in the ingest_jobs.status column; the api's
    /diagnostics page surfaces them.
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
