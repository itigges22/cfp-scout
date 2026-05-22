"""/api/v1/config — XLSX workbook import/export (plan 31).

Endpoints:
  * ``GET  /config/workbook-template``  — empty XLSX with Reference + samples
  * ``GET  /config/export-workbook``    — current DB state as XLSX
  * ``POST /config/preview-import``     — dry-run; returns diff JSON
  * ``POST /config/import-workbook``    — apply (refuses if errors / deletes
                                          require confirm_deletes match)

Body for preview-import + import-workbook: multipart form, key ``file``,
content type ``application/vnd.openxmlformats-officedocument.spreadsheetml.sheet``.

The route layer enforces:
  * File size cap 5MB
  * MIME sniffing (the first 4 bytes of a valid XLSX are ``PK\x03\x04``)
  * Refuses to apply when the diff has errors
  * Requires ``confirm_deletes=N`` when the diff has N>0 delete plans
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from app.db.session import DbSession
from app.services.workbook import (
    apply_diff,
    build_current_state_workbook,
    build_empty_template,
    compute_diff,
    parse_workbook,
)

log = structlog.get_logger("scout.api.config")
router = APIRouter(prefix="/api/v1/config", tags=["config"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Read-only download endpoints
# ---------------------------------------------------------------------------
@router.get("/workbook-template")
async def workbook_template() -> Response:
    """Empty XLSX with all sheets, a Reference sheet, and a single sample
    row per sheet demonstrating each column's format."""
    payload = build_empty_template()
    return Response(
        content=payload,
        media_type=_XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="scout-config-template.xlsx"',
        },
    )


@router.get("/export-workbook")
async def export_workbook(db: DbSession) -> Response:
    """Current DB state as an XLSX. Round-trip identity: re-importing
    without edits is a no-op."""
    payload = await build_current_state_workbook(db)
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return Response(
        content=payload,
        media_type=_XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="scout-config-{today}.xlsx"',
        },
    )


# ---------------------------------------------------------------------------
# Write endpoints (preview + apply)
# ---------------------------------------------------------------------------
@router.post("/preview-import")
async def preview_import(db: DbSession, file: UploadFile = File(...)) -> dict:
    """Dry-run: parse + diff. Never commits. Returns the JSON
    DiffResult so the UI can render the preview pane."""
    content = await _read_and_validate(file)
    parsed = parse_workbook(content)
    diff = await compute_diff(db, parsed)
    log.info(
        "config.preview_import",
        inserts=diff.summary["inserts"],
        updates=diff.summary["updates"],
        deletes=diff.summary["deletes"],
        errors=diff.summary["errors"],
    )
    return diff.to_dict()


@router.post("/import-workbook", status_code=status.HTTP_200_OK)
async def import_workbook(
    db: DbSession,
    file: UploadFile = File(...),
    confirm_deletes: int = Form(default=0, ge=0),
    actor_label: str = Form(default="workbook_import"),
) -> dict:
    """Apply the workbook to the DB inside a single transaction.

    Errors:
      * 400 — file too large / wrong MIME / corrupt XLSX
      * 422 — diff has errors (call /preview-import first to see them)
      * 409 — deletes present but ``confirm_deletes`` doesn't match
    """
    content = await _read_and_validate(file)
    parsed = parse_workbook(content)
    diff = await compute_diff(db, parsed)

    if diff.has_errors:
        log.warning("config.import.refused", errors=diff.summary["errors"])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "diff has errors; fix the workbook + re-upload",
                **diff.to_dict(),
            },
        )

    declared_deletes = diff.summary["deletes"]
    if declared_deletes != confirm_deletes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"diff contains {declared_deletes} delete(s) but "
                f"confirm_deletes={confirm_deletes}. Resubmit with "
                f"confirm_deletes={declared_deletes} to apply."
            ),
        )

    full_label = (
        f"{actor_label}:{file.filename}:{datetime.now(tz=UTC).isoformat(timespec='seconds')}"
    )
    result = await apply_diff(db, diff, actor_label=full_label)
    await db.commit()
    log.info("config.import.applied", **result.to_dict(), actor=full_label)
    return {
        "applied": result.to_dict(),
        "summary": diff.summary,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
async def _read_and_validate(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file > {_MAX_UPLOAD_BYTES // 1024 // 1024}MB",
        )
    # XLSX is a ZIP container — magic bytes PK\x03\x04. Cheap sanity check
    # before openpyxl chokes on a non-XLSX upload.
    if len(content) < 4 or content[:4] != b"PK\x03\x04":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="not a valid XLSX file (missing ZIP magic bytes)",
        )
    return content
