"""Empty workbook template generator (plan 31).

Builds an XLSX with:
  * A `Reference` sheet explaining cell conventions + per-sheet column
    notes.
  * One sheet per ``SheetSpec`` with just the header row + a single
    sample row demonstrating the format.

Used by ``GET /api/v1/config/workbook-template`` and by the unmodified-
template round-trip test.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.services.workbook._schema import SHEET_SPECS, SheetSpec

# Cosmetic constants. openpyxl widths are roughly char-units.
_HEADER_FILL = PatternFill("solid", fgColor="1F2937")
_HEADER_FONT = Font(bold=True, color="F9FAFB")
_NOTE_FONT = Font(italic=True, color="6B7280")


def build_empty_template() -> bytes:
    wb = Workbook()
    # Default sheet from Workbook() — repurpose as Reference.
    ref = wb.active
    ref.title = "Reference"
    _build_reference_sheet(ref)

    for spec in SHEET_SPECS:
        ws = wb.create_sheet(spec.name)
        _write_header(ws, spec)
        _write_sample_row(ws, spec)
        _set_column_widths(ws, spec)

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Reference sheet
# ---------------------------------------------------------------------------
def _build_reference_sheet(ws) -> None:
    ws.merge_cells("A1:C1")
    ws["A1"] = "Scout configuration workbook"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A2"] = (
        "One sheet per entity. Edit in Google Sheets, then export as XLSX "
        "and upload via /settings/import-export."
    )
    ws["A2"].alignment = Alignment(wrap_text=True)

    ws["A4"] = "Cell conventions"
    ws["A4"].font = Font(bold=True, size=12)
    conv_rows = [
        ("Type", "Format", "Example"),
        ("Text", "UTF-8 plain", "Senior ML Engineers"),
        ("List (text[])", "Semicolon-separated, no trailing ;", "RAG; Embeddings; Vector DBs"),
        ("Boolean", "TRUE / FALSE (case-insensitive)", "TRUE"),
        ("Date", "YYYY-MM-DD", "2026-09-15"),
        ("Enum", "Exact-match (lowercase)", "executive"),
        ("ISO country", "ISO-3166-1 alpha-2", "US"),
        ("UUID", "Round-trip identifier; leave blank on insert", ""),
    ]
    for row in conv_rows:
        ws.append(row)
    # Style the conventions header
    for cell in ws[5]:
        cell.font = Font(bold=True)

    ws.append([])
    ws.append(["Action column"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)
    action_rows = [
        ("Value", "Meaning"),
        ("upsert (default)", "Insert if _scout_id is blank; update if it matches an existing row."),
        ("delete", "Soft-delete the row (is_active=false). Requires typed-count confirm on apply."),
        ("skip", "Ignore this row entirely. Useful for parking work in progress."),
    ]
    for row in action_rows:
        ws.append(row)

    ws.append([])
    ws.append(["Safety"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)
    ws.append(
        ["Cells starting with =, +, -, @ are rejected on import (formula-injection defense)."]
    )
    ws.append(
        ["Rows present in DB but missing from the upload are KEPT (no auto-delete from omission)."]
    )
    ws.append(["Formulas are never executed: cells with formulas trigger a hard error on import."])

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 40


# ---------------------------------------------------------------------------
# Per-sheet header + sample row
# ---------------------------------------------------------------------------
def _write_header(ws, spec: SheetSpec) -> None:
    headers = spec.column_names()
    ws.append(headers)
    for col_idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.freeze_panes = "A2"

    # Per-column note row directly under the header.
    note_row = [c.note or "" for c in spec.columns]
    ws.append(note_row)
    for col_idx, _ in enumerate(note_row, start=1):
        ws.cell(row=2, column=col_idx).font = _NOTE_FONT
        ws.cell(row=2, column=col_idx).alignment = Alignment(wrap_text=True, vertical="top")


def _write_sample_row(ws, spec: SheetSpec) -> None:
    sample = _SAMPLE_ROWS.get(spec.name)
    if not sample:
        return
    ordered = [sample.get(c.name, "") for c in spec.columns]
    ws.append(ordered)


_SAMPLE_ROWS: dict[str, dict[str, object]] = {
    "Pillars": {
        "name": "Sample — Trusted Open Source AI",
        "description": "Pillar focused on enterprise-grade open AI tooling.",
        "display_order": 1,
    },
    "Industries": {
        "name": "Sample — Tech",
    },
    "Audiences": {
        "name": "Sample — Platform Engineering Leaders",
        "industry": "Tech",
        "role_seniority": "director",
        "description": (
            "Sample audience: leaders responsible for the developer "
            "infrastructure and AI runtime platforms at midsize-to-large "
            "enterprises."
        ),
        "primary_pain_points": "Platform sprawl; Hard to measure platform ROI",
        "key_messages": "Open source by default; Standardize on Kubernetes",
        "exclusion_criteria": "",
        "is_active": "TRUE",
    },
    "SMEs": {
        "full_name": "Sample — Alice Chen",
        "email": "alice@example.com",
        "team": "DAAM",
        "expertise_areas": "Retrieval-augmented generation; Vector databases",
        "primary_topics": "rag; llm",
        "audience_focus": "Platform Engineering Leaders",
        "location_country": "US",
        "location_city": "Boston",
        "bio": (
            "Sample bio: 10+ years platform engineering, last three on "
            "retrieval-augmented generation systems at scale. Frequent "
            "speaker on RAG architecture, vector databases, and inference "
            "operationalization for enterprise platforms."
        ),
        "linkedin_url": "https://www.linkedin.com/in/example",
        "github_url": "",
        "website_url": "",
        "is_active": "TRUE",
    },
    "Topics": {
        "name": "Sample — RAG",
        "slug": "rag",
        "aliases": "Retrieval-Augmented Generation",
        "is_active": "TRUE",
        "pending_review": "FALSE",
    },
    "Series": {
        "canonical_name": "Sample — Made-Up Conference",
        "aliases": "MUC; My Mock Conf",
        "description": "Example series row; delete before importing.",
        "typical_month": 9,
        "typical_topics": "fictitious; sample",
        "homepage": "https://example.invalid",
        "is_active": "TRUE",
    },
}


def _set_column_widths(ws, spec: SheetSpec) -> None:
    """Reasonable starting widths so the template opens nicely in Sheets."""
    from openpyxl.utils import get_column_letter

    widths = {
        "_scout_id": 36,
        "_action": 10,
        "name": 30,
        "full_name": 28,
        "canonical_name": 28,
        "description": 60,
        "bio": 70,
        "primary_pain_points": 50,
        "key_messages": 50,
        "exclusion_criteria": 40,
        "expertise_areas": 50,
        "primary_topics": 40,
        "audience_focus": 40,
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
    }
    for idx, col in enumerate(spec.columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = widths.get(col.name, 22)
