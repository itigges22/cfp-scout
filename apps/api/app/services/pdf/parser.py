"""Docling wrapper: PDF (or other supported format) → structured chunks.

Docling does both the parsing (`DocumentConverter`) and the structural
chunking (`HybridChunker`). We hold module-level singletons for both because
construction is expensive (model loads).

Both Docling APIs are synchronous, so callers must invoke ``parse_and_chunk``
via ``fastapi.concurrency.run_in_threadpool`` to keep the event loop free.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.services.embeddings.chunker import ChunkData

log = structlog.get_logger("scout.pdf.parser")

# Lazily-instantiated singletons. Building them downloads models the first
# time and takes 10-60s. Subsequent calls reuse the loaded instance.
_converter: Any | None = None
_chunker: Any | None = None


def _get_converter() -> Any:
    global _converter
    if _converter is None:
        # Local import — Docling pulls in heavy ML deps; we don't want them
        # loaded at module import time for unrelated routes.
        from docling.document_converter import DocumentConverter

        log.info("docling.converter.init.begin")
        _converter = DocumentConverter()
        log.info("docling.converter.init.done")
    return _converter


def _get_chunker() -> Any:
    global _chunker
    if _chunker is None:
        from docling.chunking import HybridChunker

        log.info("docling.chunker.init.begin")
        _chunker = HybridChunker()
        log.info("docling.chunker.init.done")
    return _chunker


@dataclass(slots=True)
class ParsedPdf:
    """What ``parse_and_chunk`` returns to the pipeline layer."""

    full_text: str
    chunks: list[ChunkData]
    page_count: int


def parse_and_chunk(path: Path) -> ParsedPdf:
    """Parse `path` with Docling, chunk via HybridChunker.

    Returns ChunkData rows whose ``metadata`` carries per-chunk structural
    info pulled out of Docling: page numbers, the nearest section heading,
    and the content type (text / table / list / etc.). Plan-22 agent chat
    uses this metadata to cite "page 4, section 'Audience profiles'" rather
    than the opaque "chunk N".

    Synchronous — wrap in run_in_threadpool from the route handler.
    """
    converter = _get_converter()
    result = converter.convert(str(path))
    doc = result.document  # DoclingDocument

    full_text = doc.export_to_markdown()
    page_count = _count_pages(doc)

    chunker = _get_chunker()
    docling_chunks = list(chunker.chunk(doc))

    chunks: list[ChunkData] = []
    for index, dc in enumerate(docling_chunks):
        text = dc.text if hasattr(dc, "text") else str(dc)
        metadata = _extract_chunk_metadata(dc)
        chunks.append(
            ChunkData(
                text=text,
                chunk_index=index,
                token_count=max(1, len(text) // 4),
                metadata=metadata,
            )
        )

    log.info(
        "docling.parse.done",
        path=str(path),
        pages=page_count,
        chunks=len(chunks),
        markdown_chars=len(full_text),
    )
    return ParsedPdf(full_text=full_text, chunks=chunks, page_count=page_count)


# ---------------------------------------------------------------------------
# Helpers — defensive about Docling's evolving internal types.
# ---------------------------------------------------------------------------
def _count_pages(doc: Any) -> int:
    """DoclingDocument exposes pages in a few different ways across versions.
    Try the common ones and fall back to 0 rather than crashing."""
    try:
        if hasattr(doc, "pages") and doc.pages is not None:
            pages = doc.pages
            if hasattr(pages, "__len__"):
                return len(pages)
            return sum(1 for _ in pages)
    except Exception:  # noqa: BLE001 — Docling internals vary across releases
        pass
    return 0


def _extract_chunk_metadata(chunk: Any) -> dict[str, Any]:
    """Best-effort metadata extraction from a Docling chunk.

    Docling's chunk shape has shifted across versions; we pull what we can.
    Anything missing just becomes a missing key in the dict — callers must
    tolerate.
    """
    metadata: dict[str, Any] = {}

    meta = getattr(chunk, "meta", None)
    if meta is None:
        return metadata

    # Section heading — recent Docling exposes heading via meta.headings.
    headings = getattr(meta, "headings", None)
    if headings:
        # Take the deepest heading (most specific).
        metadata["section_heading"] = (
            headings[-1] if isinstance(headings, (list, tuple)) else str(headings)
        )

    # Page number — from doc_items[0].prov[0].page_no in newer versions.
    page_no = _extract_page_no(meta)
    if page_no is not None:
        metadata["page_number"] = page_no

    # Content type — table / text / list / etc.
    content_type = getattr(meta, "label", None) or getattr(meta, "type", None)
    if content_type:
        metadata["content_type"] = str(content_type)

    return metadata


def _extract_page_no(meta: Any) -> int | None:
    """Walk the messy nested structure to find a page number. None if absent."""
    doc_items = getattr(meta, "doc_items", None) or []
    for item in doc_items:
        prov = getattr(item, "prov", None) or []
        for p in prov:
            page = getattr(p, "page_no", None) or getattr(p, "page", None)
            if isinstance(page, int):
                return page
    return None
