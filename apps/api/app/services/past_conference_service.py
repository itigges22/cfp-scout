"""Past-conferences service. CRUD + CSV import.

The CSV import lives here because the row-by-row resolution (name → SME UUID,
free-form ``attended_by_names`` → ``attended_sme_ids``) is business logic.
"""

from __future__ import annotations

import csv
from io import StringIO
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import PastConference, Sme
from app.schemas.common import Page
from app.schemas.past_conference import (
    PastConferenceCreate,
    PastConferenceCSVRow,
    PastConferenceRead,
    PastConferenceUpdate,
)
from app.services._common import model_to_audit_dict, paginate, write_audit


async def _resolve_sme_ids(db: AsyncSession, ids: list[UUID]) -> None:
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="attended_sme_ids cannot be empty",
        )
    count = (
        await db.execute(select(func.count(Sme.id)).where(Sme.id.in_(ids), Sme.is_active.is_(True)))
    ).scalar_one()
    if int(count) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="one or more attended_sme_ids do not exist or are inactive",
        )


async def list_past_conferences(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    q: str | None = None,
    year: int | None = None,
) -> Page[PastConferenceRead]:
    stmt = select(PastConference).order_by(PastConference.year.desc(), PastConference.name.asc())
    if q:
        stmt = stmt.where(PastConference.name.ilike(f"%{q}%"))
    if year is not None:
        stmt = stmt.where(PastConference.year == year)

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[PastConferenceRead](
        items=[PastConferenceRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_past_conference(db: AsyncSession, pc_id: UUID) -> PastConference:
    obj = await db.get(PastConference, pc_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"past_conference {pc_id} not found",
        )
    return obj


async def create_past_conference(
    db: AsyncSession,
    payload: PastConferenceCreate,
    *,
    actor_label: str = "system",
) -> PastConference:
    await _resolve_sme_ids(db, payload.attended_sme_ids)

    obj = PastConference(**payload.model_dump())
    db.add(obj)
    await db.flush()

    await write_audit(
        db,
        action="create",
        target_type="past_conference",
        target_id=obj.id,
        before=None,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


async def update_past_conference(
    db: AsyncSession,
    pc_id: UUID,
    payload: PastConferenceUpdate,
    *,
    actor_label: str = "system",
) -> PastConference:
    obj = await get_past_conference(db, pc_id)
    before = model_to_audit_dict(obj)

    await _resolve_sme_ids(db, payload.attended_sme_ids)

    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    await db.flush()
    # See audience_service.update_audience_profile for the rationale.
    await db.refresh(obj)

    await write_audit(
        db,
        action="update",
        target_type="past_conference",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------
# Canonical CSV columns: name, year, attended_by_names, role, session_type, notes
# attended_by_names is semicolon-separated; resolved by matching
# (case-insensitive, whitespace-normalised) against Sme.full_name.
# All-or-nothing transaction unless ?ignore_errors=true is passed by the route.


async def _resolve_names_to_sme_ids(
    db: AsyncSession, names: list[str]
) -> tuple[list[UUID], list[str]]:
    """Return (resolved_ids, unknown_names). Order-preserving on inputs."""
    if not names:
        return [], []
    normalized = [n.strip().lower() for n in names if n.strip()]
    rows = (
        await db.execute(
            select(Sme.id, Sme.full_name).where(
                func.lower(Sme.full_name).in_(normalized),
                Sme.is_active.is_(True),
            )
        )
    ).all()
    by_name: dict[str, UUID] = {full_name.strip().lower(): _id for _id, full_name in rows}
    resolved: list[UUID] = []
    unknown: list[str] = []
    for name in normalized:
        if name in by_name:
            resolved.append(by_name[name])
        else:
            unknown.append(name)
    return resolved, unknown


class ImportResult(dict):
    """Stub typed-dict-style return; route surfaces this as JSON."""


async def import_past_conferences_csv(
    db: AsyncSession,
    csv_bytes: bytes,
    *,
    ignore_errors: bool = False,
    actor_label: str = "csv_import",
) -> dict[str, object]:
    """Parse + validate + insert in one transaction.

    Returns a summary: ``{imported, skipped, errors: [{row, field, message}]}``.
    Any error aborts the whole import unless ``ignore_errors=True``.
    """
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(StringIO(text))

    errors: list[dict[str, str | int]] = []
    valid_rows: list[tuple[int, PastConferenceCSVRow, list[UUID]]] = []

    for line_no, raw in enumerate(reader, start=2):  # +1 for header
        # Strip whitespace + quote leading formula-injection chars.
        cleaned = {
            k: _quote_formula(v.strip()) if isinstance(v, str) else v
            for k, v in raw.items()
            if k is not None
        }

        # Validate against the CSV-row schema. Catches missing/long fields,
        # bad enums, bad years.
        try:
            row = PastConferenceCSVRow(**cleaned)
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(
                    {
                        "row": line_no,
                        "field": ".".join(str(p) for p in err["loc"]),
                        "message": err["msg"],
                    }
                )
            continue

        names = [n.strip() for n in row.attended_by_names.split(";") if n.strip()]
        resolved, unknown = await _resolve_names_to_sme_ids(db, names)
        if unknown:
            errors.append(
                {
                    "row": line_no,
                    "field": "attended_by_names",
                    "message": f"unknown SME name(s): {', '.join(unknown)}",
                }
            )
            continue

        valid_rows.append((line_no, row, resolved))

    if errors and not ignore_errors:
        return {
            "imported": 0,
            "skipped": len(errors),
            "errors": errors,
            "note": "no rows inserted; pass ?ignore_errors=true to commit valid rows only",
        }

    imported = 0
    for _line_no, row, resolved_ids in valid_rows:
        obj = PastConference(
            name=row.name,
            year=row.year,
            attended_sme_ids=resolved_ids,
            role=row.role,
            session_type=row.session_type,
            notes=row.notes or "",
            imported_from="csv_import",
        )
        db.add(obj)
        imported += 1

    if imported:
        await db.flush()
        # Single bulk audit entry — per-row audits would balloon noise.
        await write_audit(
            db,
            action="bulk_import",
            target_type="past_conference",
            target_id=valid_rows[0][2][0] if valid_rows[0][2] else valid_rows[0][1].name,  # type: ignore[arg-type]
            before=None,
            after={"imported_count": imported, "from": "csv"},
            actor_label=actor_label,
        )
        await db.commit()

    return {"imported": imported, "skipped": len(errors), "errors": errors}


def _quote_formula(value: str) -> str:
    """Defense against CSV formula injection: quote cells starting with `=+-@`."""
    if value and value[0] in "=+-@":
        return "'" + value
    return value
