"""One-off helper: parse the two remaining rh-docs PDFs via Docling.

Run inside the api container::

  podman exec scout-api /app/.venv/bin/python /tmp/parse_remaining_pdfs.py

Writes /tmp/writing.md and /tmp/deck.md.
"""

from __future__ import annotations

import sys

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

opts = PdfPipelineOptions()
opts.do_ocr = False
opts.do_table_structure = False  # both off → fastest path; we just want raw text

conv = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
)

TARGETS = [
    ("/tmp/Writing for <vendor> Notes.pdf", "/tmp/writing.md"),
    ("/tmp/the AI platform _ Customer Deck.pdf", "/tmp/deck.md"),
]

for src, out in TARGETS:
    print(f"START {src}", flush=True)
    try:
        md = conv.convert(src).document.export_to_markdown()
        with open(out, "w") as fh:
            fh.write(md)
        print(f"OK    {src} -> {out} ({len(md):,} chars)", flush=True)
    except Exception as e:
        print(f"FAIL  {src}: {type(e).__name__}: {e}", flush=True)
        import traceback

        traceback.print_exc()

print("DONE", flush=True)
sys.exit(0)
