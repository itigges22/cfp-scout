"""Docling wrapper: PDF (or other supported format) → structured chunks.

Docling does both the parsing (`DocumentConverter`) and the structural
chunking (`HybridChunker`). We hold module-level singletons for both
because construction is expensive (model loads). Each pipeline tier
gets its own converter; small PDFs use the full Docling pipeline
(layout + table-structure + OCR), large ones drop the expensive bits
to stay inside the api container's memory budget.

Both Docling APIs are synchronous, so callers must invoke
``parse_and_chunk`` via ``fastapi.concurrency.run_in_threadpool`` to
keep the event loop free.

Tiering by file size, sized for a 6 GB api container:

  * small  (< 4 MB) — full Docling pipeline. Layout + table structure
                      + OCR. Best fidelity; ~1.5 GB resident.
  * medium (4–10 MB) — Docling minus OCR. Still gets layout + tables.
                      Most product PDFs land here; ~1.7 GB resident.
  * large  (> 10 MB) — Docling text-only. No OCR, no table structure.
                      Slide decks and giant whitepapers; ~1.2 GB
                      resident, plus headroom for the doc itself.
  * fallback        — if the chosen Docling tier raises (or the worker
                      is killed and a retry lands here), we strip
                      down further by re-trying at the next-smaller
                      tier; if every tier fails we surface a clear
                      ``PdfParseError`` instead of returning empty
                      chunks silently.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

from app.services.embeddings.chunker import ChunkData

log = structlog.get_logger("scout.pdf.parser")

# File-size thresholds that pick a Docling pipeline tier. Tunable via
# settings.py overrides if the heuristics need adjusting for a fleet's
# document mix.
SMALL_THRESHOLD_BYTES = 4 * 1024 * 1024  # 4 MB
LARGE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB

PipelineTier = Literal["small", "medium", "large", "text_only"]


class PdfParseError(RuntimeError):
    """All pipeline tiers failed for this PDF."""


# Per-tier subprocess timeouts in seconds. Tunable here; defaults sized
# for the api container's 2 CPUs.
_TIER_TIMEOUT_SECONDS: dict[PipelineTier, int] = {
    # Sized for an api container that may be sharing 4 GiB with the model
    # weight cache. Docling makes steady progress but pages of layout
    # extraction take real wall-clock on CPU — bigger PDFs proportionally.
    "small": 600,
    "medium": 600,
    "large": 600,
    "text_only": 120,
}

# Path to the worker module. Resolved once at import time so we don't
# pay the filesystem lookup per parse.
_WORKER_PATH = str(Path(__file__).parent / "_docling_worker.py")


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
