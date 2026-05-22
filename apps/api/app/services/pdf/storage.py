"""On-disk PDF storage.

Files are saved under ``STORAGE_PATH/pdf_uploads/<uuid>.pdf`` (the named
volume in compose.yaml). Original filenames are kept only as metadata —
the on-disk path is a generated UUID to defeat path-traversal and
filename-collision attacks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import structlog

from app.settings import get_settings

log = structlog.get_logger("scout.pdf.storage")


# MIME sniff: real PDFs start with "%PDF-". Cheap + reliable signal.
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
