"""Current-state workbook export (plan 31).

Mirrors ``template.py``'s structure but with every DB row written into the
appropriate sheet. Used by ``GET /api/v1/config/export-workbook``.

Round-trip identity contract: exporting + re-importing without edits
produces zero changes. The `_scout_id` column + the sheet-spec column
order are the keys to that guarantee.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    AudienceProfile,
    ConferenceSeries,
    Sme,
    StrategicPillar,
    Topic,
)
from app.services.workbook._cells import (
    fmt_bool,
    fmt_int,
    fmt_list_text,
    fmt_str,
    fmt_uuid,
)
from app.services.workbook._schema import SHEET_SPECS, SheetSpec

_HEADER_FILL = PatternFill("solid", fgColor="1F2937")
_HEADER_FONT = Font(bold=True, color="F9FAFB")


async def build_current_state_workbook(db: AsyncSession) -> bytes:
    """Build an XLSX populated with the current DB state."""
    wb = Workbook()
    ref = wb.active
    ref.title = "Reference"
    _build_reference_brief(ref)

    # Index of audience IDs → names + topic IDs → names so the SMEs sheet can
    # serialize references as human-readable names rather than UUIDs.
    audiences_by_id, topics_by_id = await _build_lookups(db)

    for spec in SHEET_SPECS:
        ws = wb.create_sheet(spec.name)
        _write_header(ws, spec)
        rows = await _rows_for_sheet(db, spec, audiences_by_id, topics_by_id)
        for row in rows:
            ordered = [row.get(c.name, "") for c in spec.columns]
            ws.append(ordered)
        _autosize(ws, spec)

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Per-sheet row builders
# ---------------------------------------------------------------------------
async def _rows_for_sheet(
    db: AsyncSession,
    spec: SheetSpec,
    audiences_by_id: dict,
    topics_by_id: dict,
) -> list[dict]:
    if spec.name == "Pillars":
        rows = (
            (await db.execute(select(StrategicPillar).order_by(StrategicPillar.display_order)))
            .scalars()
            .all()
        )
        return [
            {
                "_scout_id": fmt_uuid(r.id),
                "_action": "",
                "name": fmt_str(r.name),
                "description": fmt_str(r.description),
                "display_order": fmt_int(r.display_order),
            }
            for r in rows
        ]

    if spec.name == "Industries":
        # No DB table — derive distinct industries from active audiences.
        rows = (
            await db.execute(
                select(AudienceProfile.industry)
                .where(AudienceProfile.is_active.is_(True))
                .distinct()
                .order_by(AudienceProfile.industry)
            )
        ).all()
        return [{"_scout_id": "", "_action": "", "name": fmt_str(r[0])} for r in rows if r[0]]

    if spec.name == "Audiences":
        rows = (
            (await db.execute(select(AudienceProfile).order_by(AudienceProfile.name)))
            .scalars()
            .all()
        )
        return [
            {
                "_scout_id": fmt_uuid(r.id),
                "_action": "",
                "name": fmt_str(r.name),
                "industry": fmt_str(r.industry),
                "role_seniority": fmt_str(r.role_seniority),
                "description": fmt_str(r.description),
                "primary_pain_points": fmt_list_text(r.primary_pain_points),
                "key_messages": fmt_list_text(r.key_messages),
                "exclusion_criteria": fmt_list_text(r.exclusion_criteria),
                "is_active": fmt_bool(r.is_active),
            }
            for r in rows
        ]

    if spec.name == "SMEs":
        rows = (await db.execute(select(Sme).order_by(Sme.full_name))).scalars().all()
        out = []
        for r in rows:
            external = r.external_links or {}
            primary_topic_names = [
                topics_by_id[t].name for t in (r.primary_topics or []) if t in topics_by_id
            ]
            audience_names = [
                audiences_by_id[a].name for a in (r.audience_focus or []) if a in audiences_by_id
            ]
            out.append(
                {
                    "_scout_id": fmt_uuid(r.id),
                    "_action": "",
                    "full_name": fmt_str(r.full_name),
                    "email": fmt_str(r.email),
                    "team": fmt_str(r.team),
                    "expertise_areas": fmt_list_text(r.expertise_areas),
                    "primary_topics": fmt_list_text(primary_topic_names),
                    "audience_focus": fmt_list_text(audience_names),
                    "location_country": fmt_str(r.location_country),
                    "location_city": fmt_str(r.location_city),
                    "bio": fmt_str(r.bio),
                    "linkedin_url": fmt_str(external.get("linkedin")),
                    "github_url": fmt_str(external.get("github")),
                    "website_url": fmt_str(external.get("website")),
                    "is_active": fmt_bool(r.is_active),
                }
            )
        return out

    if spec.name == "Topics":
        rows = (await db.execute(select(Topic).order_by(Topic.name))).scalars().all()
        return [
            {
                "_scout_id": fmt_uuid(r.id),
                "_action": "",
                "name": fmt_str(r.name),
                "slug": fmt_str(r.slug),
                "aliases": fmt_list_text(r.aliases),
                "is_active": fmt_bool(r.is_active),
                "pending_review": fmt_bool(r.pending_review),
            }
            for r in rows
        ]

    if spec.name == "Series":
        rows = (
            (await db.execute(select(ConferenceSeries).order_by(ConferenceSeries.canonical_name)))
            .scalars()
            .all()
        )
        return [
            {
                "_scout_id": fmt_uuid(r.id),
                "_action": "",
                "canonical_name": fmt_str(r.canonical_name),
                "aliases": fmt_list_text(r.aliases),
                "description": fmt_str(r.description),
                "typical_month": fmt_int(r.typical_month),
                "typical_topics": fmt_list_text(r.typical_topics),
                "homepage": fmt_str(r.homepage),
                "is_active": fmt_bool(r.is_active),
            }
            for r in rows
        ]

    return []


# ---------------------------------------------------------------------------
# Lookups + chrome
# ---------------------------------------------------------------------------
async def _build_lookups(db: AsyncSession) -> tuple[dict, dict]:
    auds = (await db.execute(select(AudienceProfile))).scalars().all()
    tops = (await db.execute(select(Topic))).scalars().all()
    return ({a.id: a for a in auds}, {t.id: t for t in tops})


def _build_reference_brief(ws) -> None:
    ws["A1"] = "Scout configuration — current export"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Sheets below contain a snapshot of the DB. Edit + re-import to apply changes."
    ws["A4"] = "Round-trip rule"
    ws["A4"].font = Font(bold=True)
    ws["A5"] = "Importing this file with no edits is a no-op."
    ws["A6"] = "Rows present in DB but missing from your upload are KEPT (no auto-delete)."
    ws["A7"] = "Use _action=delete to soft-delete (requires typed-count confirm on apply)."
    ws.column_dimensions["A"].width = 80


def _write_header(ws, spec: SheetSpec) -> None:
    headers = spec.column_names()
    ws.append(headers)
    for idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=idx)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.freeze_panes = "A2"


def _autosize(ws, spec: SheetSpec) -> None:
    widths = {
        "_scout_id": 36,
        "_action": 10,
        "name": 32,
        "full_name": 28,
        "canonical_name": 30,
        "description": 60,
        "bio": 80,
        "primary_pain_points": 50,
        "key_messages": 50,
        "expertise_areas": 50,
        "primary_topics": 36,
        "audience_focus": 36,
        "aliases": 40,
        "typical_topics": 40,
        "email": 28,
        "team": 14,
        "industry": 22,
        "role_seniority": 14,
        "location_country": 16,
        "location_city": 20,
        "linkedin_url": 36,
        "github_url": 36,
        "website_url": 36,
        "homepage": 36,
        "slug": 22,
        "typical_month": 14,
        "is_active": 10,
        "pending_review": 16,
        "display_order": 14,
        "exclusion_criteria": 36,
    }
    for idx, col in enumerate(spec.columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = widths.get(col.name, 22)
