"""The throwaway process that actually runs Docling.

WHAT THIS DOES
    A tiny standalone script: given a PDF path and a tier name, it builds the
    matching Docling converter, parses and chunks the document, and prints
    one line of JSON — ``{"full_text": ..., "chunks": [...],
    "page_count": N}`` — to stdout.

HOW IT CONNECTS
    Called by   services/pdf.py, spawned with ``python pdf_worker.py
                <pdf_path> <tier>``. Nothing imports it.
    Reads       the PDF file it is given
    Helpers     docling, imported lazily inside the worker
    Tuning      tier ∈ {small, medium, large}, chosen by the parent

WORTH KNOWING
    Living in its own process is the whole point: Docling's models can push
    memory far enough that the kernel's out-of-memory killer steps in, and
    that must not take the API down with it. Any non-zero exit, 137 included,
    simply tells the parent to try a lighter tier — so this script should
    fail by exiting, never by printing partial JSON.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _build_converter(tier: str) -> Any:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    if tier == "small":
        opts.do_ocr = True
        opts.do_table_structure = True
    elif tier == "medium":
        opts.do_ocr = False
        opts.do_table_structure = True
    elif tier == "large":
        opts.do_ocr = False
        opts.do_table_structure = False
    else:
        raise ValueError(f"unknown tier: {tier}")
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def _count_pages(doc: Any) -> int:
    try:
        if hasattr(doc, "pages") and doc.pages is not None:
            pages = doc.pages
            if hasattr(pages, "__len__"):
                return len(pages)
            return sum(1 for _ in pages)
    except Exception:
        pass
    return 0


def _extract_chunk_metadata(chunk: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    meta = getattr(chunk, "meta", None)
    if meta is None:
        return metadata
    headings = getattr(meta, "headings", None)
    if headings:
        metadata["section_heading"] = (
            headings[-1] if isinstance(headings, list | tuple) else str(headings)
        )
    doc_items = getattr(meta, "doc_items", None) or []
    for item in doc_items:
        prov = getattr(item, "prov", None) or []
        for p in prov:
            page = getattr(p, "page_no", None) or getattr(p, "page", None)
            if isinstance(page, int):
                metadata["page_number"] = page
                break
        if "page_number" in metadata:
            break
    content_type = getattr(meta, "label", None) or getattr(meta, "type", None)
    if content_type:
        metadata["content_type"] = str(content_type)
    return metadata


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: pdf_worker.py <pdf_path> <tier>", file=sys.stderr)
        return 2

    pdf_path, tier = sys.argv[1], sys.argv[2]

    # Local import so failure to import Docling reports cleanly via stderr.
    from docling.chunking import HybridChunker

    converter = _build_converter(tier)
    result = converter.convert(pdf_path)
    doc = result.document

    full_text = doc.export_to_markdown()
    page_count = _count_pages(doc)

    chunker = HybridChunker()
    docling_chunks = list(chunker.chunk(doc))

    chunks: list[dict[str, Any]] = []
    for index, dc in enumerate(docling_chunks):
        text = dc.text if hasattr(dc, "text") else str(dc)
        chunks.append(
            {
                "text": text,
                "chunk_index": index,
                "token_count": max(1, len(text) // 4),
                "metadata": _extract_chunk_metadata(dc),
            }
        )

    json.dump(
        {"full_text": full_text, "chunks": chunks, "page_count": page_count},
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
