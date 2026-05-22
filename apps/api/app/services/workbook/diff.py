"""Per-sheet diff between a parsed workbook and the current DB (plan 31).

Inputs: ``ParsedWorkbook`` from reader.py + a live AsyncSession.
Output: ``DiffResult`` with per-sheet insert/update/delete plans + the
combined error list. The apply layer takes the same DiffResult and
commits, atomically, when the operator confirms.

Rules (from plan-31):
  * `_scout_id` blank → INSERT
  * `_scout_id` matches an existing row → UPDATE
  * `_scout_id` doesn't match any row → ERROR (no silent inserts on bad UUIDs)
  * `_action=delete` → SOFT-DELETE (requires typed-count confirm at apply time)
  * `_action=skip` → ignore the row entirely
  * Row present in DB but missing from the upload → KEEP (never auto-delete)

Cross-sheet validation:
  * SMEs.primary_topics name-references must resolve against the Topics
    sheet (preferred) or existing DB Topic rows.
  * SMEs.audience_focus name-references must resolve against the Audiences
    sheet (preferred) or existing DB AudienceProfile rows.
  * Audiences.industry must be a value present on the Industries sheet
    OR an industry already in use by a DB AudienceProfile row.

The diff layer is otherwise pure: it produces a Plan, doesn't touch the DB.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    AudienceProfile,
    ConferenceSeries,
    Sme,
    StrategicPillar,
    Topic,
)
from app.services.workbook.reader import ParsedWorkbook, SheetRowError


@dataclass(slots=True)
class RowPlan:
    """One row's plan after diffing — what apply.py will do with it."""

    sheet: str
    row: int  # 1-based source row (for UI error display)
    action: str  # 'insert' / 'update' / 'delete'
    scout_id: str | None  # set for update/delete; None for insert
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiffResult:
    """Summary + per-sheet plans + errors. UI uses summary for the preview
    pane; apply.py walks the per-sheet plans."""

    summary: dict = field(
        default_factory=lambda: {
            "inserts": 0,
            "updates": 0,
            "deletes": 0,
            "errors": 0,
        }
    )
    by_sheet: dict[str, dict] = field(default_factory=dict)
    plans_by_sheet: dict[str, list[RowPlan]] = field(default_factory=dict)
    errors: list[SheetRowError] = field(default_factory=list)
    unknown_sheets: list[str] = field(default_factory=list)
    file_errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return self.summary["errors"] > 0 or bool(self.file_errors)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "by_sheet": self.by_sheet,
            "errors": [
                {
                    "sheet": e.sheet,
                    "row": e.row,
                    "field": e.field,
                    "value": e.value,
                    "message": e.message,
                }
                for e in self.errors
            ],
            "unknown_sheets": self.unknown_sheets,
            "file_errors": self.file_errors,
        }


async def compute_diff(db: AsyncSession, parsed: ParsedWorkbook) -> DiffResult:
    result = DiffResult()
    result.unknown_sheets = list(parsed.unknown_sheets)
    result.file_errors = list(parsed.file_errors)
    result.errors.extend(e for ps in parsed.sheets.values() for e in ps.errors)
    result.summary["errors"] = len(result.errors)

    # Build cross-sheet validation context.
    topics_index = await _topics_index(db, parsed)
    audiences_index = await _audiences_index(db, parsed)
    industries_set = _industries_set(parsed) | await _db_industries(db)

    for sheet_name, ps in parsed.sheets.items():
        spec_rows = ps.rows
        plans: list[RowPlan] = []
        ins = upd = dele = 0

        # Fetch the DB-side rows once per sheet (small N at our scale).
        existing = await _existing_for_sheet(db, sheet_name)

        for raw in spec_rows:
            action = raw.get("_action", "upsert")
            if action == "skip":
                continue

            scout_id: UUID | None = raw.get("_scout_id")
            row_num = _infer_row_number(ps, raw)

            # Pre-existing check.
            if scout_id is not None and scout_id not in existing:
                result.errors.append(
                    SheetRowError(
                        sheet=sheet_name,
                        row=row_num,
                        field="_scout_id",
                        value=str(scout_id),
                        message="UUID not found in DB; bad copy/paste? Leave blank to insert.",
                    )
                )
                continue

            if action == "delete":
                if scout_id is None:
                    result.errors.append(
                        SheetRowError(
                            sheet=sheet_name,
                            row=row_num,
                            field="_action",
                            value="delete",
                            message="delete requires _scout_id of an existing row.",
                        )
                    )
                    continue
                plans.append(
                    RowPlan(
                        sheet=sheet_name,
                        row=row_num,
                        action="delete",
                        scout_id=str(scout_id),
                    )
                )
                dele += 1
                continue

            # Upsert path — cross-sheet validation BEFORE classifying insert vs update.
            sheet_errors = _cross_sheet_validate(
                sheet_name=sheet_name,
                row_num=row_num,
                raw=raw,
                topics_index=topics_index,
                audiences_index=audiences_index,
                industries_set=industries_set,
            )
            if sheet_errors:
                result.errors.extend(sheet_errors)
                continue

            if scout_id is None:
                plans.append(
                    RowPlan(
                        sheet=sheet_name,
                        row=row_num,
                        action="insert",
                        scout_id=None,
                        values=dict(raw),
                    )
                )
                ins += 1
            else:
                plans.append(
                    RowPlan(
                        sheet=sheet_name,
                        row=row_num,
                        action="update",
                        scout_id=str(scout_id),
                        values=dict(raw),
                    )
                )
                upd += 1

        result.plans_by_sheet[sheet_name] = plans
        result.by_sheet[sheet_name] = {
            "inserts": ins,
            "updates": upd,
            "deletes": dele,
            "errors": sum(1 for e in result.errors if e.sheet == sheet_name),
        }
        result.summary["inserts"] += ins
        result.summary["updates"] += upd
        result.summary["deletes"] += dele

    result.summary["errors"] = len(result.errors)
    return result


# ---------------------------------------------------------------------------
# Cross-sheet validation
# ---------------------------------------------------------------------------
def _cross_sheet_validate(
    *,
    sheet_name: str,
    row_num: int,
    raw: dict,
    topics_index: dict[str, UUID],  # lower-case name -> UUID
    audiences_index: dict[str, UUID],
    industries_set: set[str],
) -> list[SheetRowError]:
    errs: list[SheetRowError] = []
    if sheet_name == "SMEs":
        for nm in raw.get("primary_topics") or []:
            if nm.lower() not in topics_index:
                errs.append(
                    SheetRowError(
                        sheet=sheet_name,
                        row=row_num,
                        field="primary_topics",
                        value=nm,
                        message="topic not found in this workbook OR DB (case-insensitive). Add it to the Topics sheet first.",
                    )
                )
        for nm in raw.get("audience_focus") or []:
            if nm.lower() not in audiences_index:
                errs.append(
                    SheetRowError(
                        sheet=sheet_name,
                        row=row_num,
                        field="audience_focus",
                        value=nm,
                        message="audience not found in this workbook OR DB. Add it to the Audiences sheet first.",
                    )
                )
    elif sheet_name == "Audiences":
        industry = raw.get("industry")
        if industry and industry not in industries_set:
            errs.append(
                SheetRowError(
                    sheet=sheet_name,
                    row=row_num,
                    field="industry",
                    value=industry,
                    message="industry not in Industries sheet OR present in DB. Add to Industries first.",
                )
            )
    return errs


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------
async def _topics_index(db: AsyncSession, parsed: ParsedWorkbook) -> dict[str, UUID]:
    """Lowercase topic-name → UUID, merged: workbook + DB."""
    out: dict[str, UUID] = {}
    db_rows = (await db.execute(select(Topic))).scalars().all()
    for r in db_rows:
        out[r.name.lower()] = r.id
    # workbook rows (insert path won't have an id yet — we use a placeholder
    # since the diff stage only needs presence-of-name, not UUID).
    placeholder = UUID(int=0)
    for r in parsed.sheets.get("Topics", _empty()).rows:
        if r.get("_action") == "skip":
            continue
        nm = r.get("name")
        if nm:
            out[nm.lower()] = r.get("_scout_id") or placeholder
    return out


async def _audiences_index(db: AsyncSession, parsed: ParsedWorkbook) -> dict[str, UUID]:
    out: dict[str, UUID] = {}
    db_rows = (await db.execute(select(AudienceProfile))).scalars().all()
    for r in db_rows:
        out[r.name.lower()] = r.id
    placeholder = UUID(int=0)
    for r in parsed.sheets.get("Audiences", _empty()).rows:
        if r.get("_action") == "skip":
            continue
        nm = r.get("name")
        if nm:
            out[nm.lower()] = r.get("_scout_id") or placeholder
    return out


def _industries_set(parsed: ParsedWorkbook) -> set[str]:
    return {
        r.get("name")
        for r in parsed.sheets.get("Industries", _empty()).rows
        if r.get("name") and r.get("_action") != "skip"
    }


async def _db_industries(db: AsyncSession) -> set[str]:
    rows = (
        await db.execute(
            select(AudienceProfile.industry).where(AudienceProfile.is_active.is_(True)).distinct()
        )
    ).all()
    return {r[0] for r in rows if r[0]}


# ---------------------------------------------------------------------------
# Existing-row maps
# ---------------------------------------------------------------------------
async def _existing_for_sheet(db: AsyncSession, sheet_name: str) -> dict[UUID, Any]:
    model = {
        "Pillars": StrategicPillar,
        "Audiences": AudienceProfile,
        "SMEs": Sme,
        "Topics": Topic,
        "Series": ConferenceSeries,
    }.get(sheet_name)
    if model is None:
        return {}  # Industries sheet has no model
    rows = (await db.execute(select(model))).scalars().all()
    return {r.id: r for r in rows}


def _infer_row_number(ps, raw: dict) -> int:
    """Best-effort: find the index of the raw row in the parsed list + 2
    (header row offset). Good enough for UI display."""
    try:
        return ps.rows.index(raw) + 2
    except ValueError:
        return 0


def _empty():
    from app.services.workbook.reader import ParsedSheet  # local import to dodge cycle

    return ParsedSheet(sheet="")


# Suppress unused warning
_ = asdict
