"""PDF ingestion via Docling.

Public surface:
    process_pdf_upload(db, *, owner_type, owner_id, file_bytes, original_filename, purpose)
        — save file to volume, parse with Docling, chunk + embed, return summary.

See ``PLANS/phase-1/12-pdf-rag-ingestion.md`` and ADR-0003 for why Docling.
"""

from app.services.pdf.pipeline import process_pdf_upload

__all__ = ["process_pdf_upload"]
