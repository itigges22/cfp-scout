"""Disk layout for raw HTML pages (plan 14).

Each fetched page's body lands at:

    <STORAGE_PATH>/raw_pages/<source_id>/<sha256>.html

Content-addressed by sha256 — a re-fetch that yields the same bytes points
at the same file, no extra disk written. Per-source subdirectory keeps the
top-level dir manageable when source counts grow.

DB rows in ``app.raw_pages`` store only path + metadata; never the body.

The mount target is configured via ``settings.storage_path`` (default
``/var/lib/scout/storage`` inside the container). The raw_pages volume is
declared in ``compose.yaml``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from app.settings import get_settings


def _raw_pages_root() -> Path:
    settings = get_settings()
    return Path(settings.storage_path) / "raw_pages"


def compute_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def save_raw_body(source_id: UUID, body: bytes, sha256: str) -> Path:
    """Write ``body`` to disk under the source's directory. Idempotent —
    re-saving the same bytes is a no-op.

    Returns the absolute path the body landed at (for ``raw_pages.raw_body_path``).
    """
    root = _raw_pages_root() / str(source_id)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{sha256}.html"
    if target.exists():
        return target
    target.write_bytes(body)
    target.chmod(0o640)
    return target
