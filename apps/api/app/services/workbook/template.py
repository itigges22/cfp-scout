"""Empty workbook template generator (plan 31).

Builds a Google-Sheets-friendly XLSX:

  * A **README** sheet (first tab) that explains what the workbook is for,
    what you can and can't change, and how to upload it back.
  * One sheet per ``SheetSpec`` with:
      - Row 1: column headers, with cell **comments** for per-column
        guidance (visible on hover in both Excel and Google Sheets).
      - Row 2: a sample row marked "Sample —" that the reader skips on
        import (so the user doesn't have to remember to delete it).
      - Enum columns get **data validation** so the cell becomes a
        dropdown picker.
      - Required columns get a different header fill from optional ones,
        and system columns (``_scout_id`` / ``_action``) are visually
        distinct from real data columns.

The reader (``apps/api/app/services/workbook/reader.py``) is the source of
truth for what's parseable — anything cosmetic added here must leave row 1
as the header and row 2+ as the data range.

Used by ``GET /api/v1/config/workbook-template``.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill, Side, Border
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from app.services.workbook._schema import SHEET_SPECS, ColumnSpec, SheetSpec

# Palette — picked so headers are legible in both Excel and Google Sheets.
_REQUIRED_FILL = PatternFill("solid", fgColor="B91C1C")  # red-700 — "you must fill this"
_OPTIONAL_FILL = PatternFill("solid", fgColor="374151")  # gray-700 — "fill if you have it"
_SYSTEM_FILL = PatternFill("solid", fgColor="64748B")  # slate-500 — managed by Scout
_HEADER_FONT = Font(bold=True, color="F9FAFB", size=11)
_SAMPLE_FILL = PatternFill("solid", fgColor="FEF3C7")  # amber-100 — "I'm a sample, delete me"
_SAMPLE_FONT = Font(italic=True, color="92400E")  # amber-800
_THIN_BORDER = Border(
    left=Side(style="thin", color="E5E7EB"),
    right=Side(style="thin", color="E5E7EB"),
    top=Side(style="thin", color="E5E7EB"),
    bottom=Side(style="thin", color="E5E7EB"),
)

# Names of the synthetic system columns — styled differently.
_SYSTEM_COLUMNS = {"_scout_id", "_action"}


def build_empty_template() -> bytes:
    wb = Workbook()
    # Default sheet from Workbook() — repurpose as README.
    readme = wb.active
    readme.title = "README"
    _build_readme_sheet(readme)

    for spec in SHEET_SPECS:
        ws = wb.create_sheet(spec.name)
        _write_header(ws, spec)
        _write_sample_row(ws, spec)
        _attach_validation(ws, spec)
        _set_column_widths(ws, spec)
        ws.sheet_view.showGridLines = True

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# README sheet — the friendly entry point
# ---------------------------------------------------------------------------
def _build_readme_sheet(ws: Worksheet) -> None:
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 90
    ws.sheet_view.showGridLines = False

    # Hero
    ws.merge_cells("A1:B1")
    ws["A1"] = "Scout — Configuration Workbook"
    ws["A1"].font = Font(bold=True, size=20, color="111827")

    ws.merge_cells("A2:B2")
    ws["A2"] = (
        "This workbook is how you tell Scout about your team — who your SMEs "
        "are, who you're trying to reach, your strategic pillars, and the "
        "conference series you care about. Edit any tab below, save, then "
        "upload at Settings → Workbook in the running app."
    )
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws["A2"].font = Font(size=11, color="374151")
    ws.row_dimensions[2].height = 50

    # How to use
    _readme_section(ws, 4, "How to use this workbook")
    _readme_para(
        ws,
        5,
        (
            "1. Open in Excel, Google Sheets, or LibreOffice — anything that "
            "reads XLSX.\n"
            "2. Click each tab at the bottom of the window. Each tab is one "
            "kind of data (Pillars, Audiences, SMEs, etc.).\n"
            "3. Replace the yellow sample row with your real data, or add "
            "new rows below it.\n"
            "4. Save as XLSX. Upload at Settings → Workbook. Scout will "
            "show you a preview of what will change before anything is "
            "written to the database."
        ),
    )

    # What you CAN change
    _readme_section(ws, 11, "What you CAN change")
    _readme_bullets(
        ws,
        12,
        [
            "Any value in any white-background cell.",
            "Add new rows below the existing data.",
            "Delete the yellow Sample rows (or leave them — the importer "
            "skips any row whose name starts with 'Sample —').",
            "Mark a row for deletion by typing 'delete' into its _action "
            "column. The row is soft-deleted (kept in the DB with "
            "is_active=false), not erased.",
            "Re-order rows freely. Order doesn't affect anything except "
            "the Pillars tab, where display_order controls it.",
        ],
    )

    # What you CAN'T change
    _readme_section(ws, 19, "What you should NOT change")
    _readme_bullets(
        ws,
        20,
        [
            "The sheet names (tabs at the bottom). The importer looks "
            "them up by name.",
            "The column names (row 1 of each tab). Renaming a column "
            "means the importer can't find it.",
            "The _scout_id column. Leave it blank on new rows; Scout "
            "fills it in when you export later.",
            "Don't add formulas (cells starting with =, +, -, @ are "
            "rejected on import for security).",
        ],
    )

    # Cell types
    _readme_section(ws, 26, "Cell types you'll see")
    type_rows = [
        ("Text", "Plain text, e.g. \"Platform Engineering Leaders\"."),
        (
            "List of text",
            "Multiple values in one cell, separated by semicolons. e.g. "
            "\"RAG; Embeddings; Vector DBs\". No trailing semicolon.",
        ),
        ("Boolean", "TRUE or FALSE (case doesn't matter)."),
        ("Number", "Whole or decimal, e.g. 1 or 0.6."),
        ("Date", "YYYY-MM-DD format, e.g. 2026-09-15."),
        (
            "Dropdown",
            "Click the cell — a dropdown arrow appears with the valid "
            "values. Used for things like role_seniority.",
        ),
        ("ISO country code", "Two letters, uppercase, e.g. US or DE."),
    ]
    for i, (label, body) in enumerate(type_rows):
        row = 27 + i
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=11)
        ws.cell(row=row, column=1).alignment = Alignment(vertical="top")
        ws.cell(row=row, column=2, value=body).alignment = Alignment(
            wrap_text=True, vertical="top"
        )

    # Header colour key
    _readme_section(ws, 36, "Header colour key")
    key_rows = [
        ("Red header", "Required — the importer rejects the row if empty.", _REQUIRED_FILL),
        ("Dark grey header", "Optional — fill in if you have the info.", _OPTIONAL_FILL),
        ("Slate header", "System columns (_scout_id, _action) — leave alone.", _SYSTEM_FILL),
        ("Yellow row", "Sample row. Replace with your data, or delete.", _SAMPLE_FILL),
    ]
    for i, (label, body, fill) in enumerate(key_rows):
        row = 37 + i
        ws.cell(row=row, column=1, value=label).fill = fill
        ws.cell(row=row, column=1).font = Font(bold=True, color="F9FAFB" if fill is not _SAMPLE_FILL else "92400E")
        ws.cell(row=row, column=2, value=body).alignment = Alignment(wrap_text=True, vertical="top")

    # Tabs in this workbook
    _readme_section(ws, 43, "Tabs in this workbook")
    for i, spec in enumerate(SHEET_SPECS):
        row = 44 + i
        ws.cell(row=row, column=1, value=spec.name).font = Font(bold=True, color="2563EB")
        ws.cell(row=row, column=2, value=spec.description).alignment = Alignment(
            wrap_text=True, vertical="top"
        )

    # Safety footer
    footer_row = 44 + len(SHEET_SPECS) + 2
    _readme_section(ws, footer_row, "Safety notes")
    _readme_bullets(
        ws,
        footer_row + 1,
        [
            "Scout shows you a preview of every change before writing to "
            "the database. You can always cancel.",
            "Rows in the database that are missing from your upload are "
            "kept, not deleted. To remove a row, you must explicitly set "
            "its _action to 'delete'.",
            "This workbook does NOT contain API keys or secrets. Those "
            "live in your .env file and the settings JSON backup "
            "(GET /api/v1/admin/settings/export).",
        ],
    )


def _readme_section(ws: Worksheet, row: int, title: str) -> None:
    ws.cell(row=row, column=1, value=title).font = Font(bold=True, size=14, color="111827")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)


def _readme_para(ws: Worksheet, row: int, body: str) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    cell = ws.cell(row=row, column=1, value=body)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    # Bump the row height to fit a few lines of wrapped text.
    line_count = body.count("\n") + 1
    ws.row_dimensions[row].height = max(20, line_count * 18)


def _readme_bullets(ws: Worksheet, start_row: int, items: list[str]) -> None:
    for i, item in enumerate(items):
        row = start_row + i
        ws.cell(row=row, column=1, value="•").alignment = Alignment(
            horizontal="right", vertical="top"
        )
        ws.cell(row=row, column=2, value=item).alignment = Alignment(
            wrap_text=True, vertical="top"
        )
        ws.row_dimensions[row].height = max(18, (len(item) // 80 + 1) * 18)


# ---------------------------------------------------------------------------
# Per-sheet header + sample row
# ---------------------------------------------------------------------------
def _write_header(ws: Worksheet, spec: SheetSpec) -> None:
    headers = spec.column_names()
    ws.append(headers)

    for col_idx, col_spec in enumerate(spec.columns, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = _THIN_BORDER
        if col_spec.name in _SYSTEM_COLUMNS:
            cell.fill = _SYSTEM_FILL
        elif col_spec.required:
            cell.fill = _REQUIRED_FILL
        else:
            cell.fill = _OPTIONAL_FILL

        cell.comment = _header_comment_for(col_spec)

    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"


def _header_comment_for(col_spec: ColumnSpec) -> Comment:
    """Build a per-column hover comment summarizing required-ness, type,
    and any spec-level note (enum values, length cap, etc.)."""
    lines: list[str] = []
    if col_spec.name in _SYSTEM_COLUMNS:
        lines.append(f"SYSTEM COLUMN — {col_spec.name}")
        lines.append("Managed by Scout. Leave blank on new rows.")
    elif col_spec.required:
        lines.append(f"REQUIRED — {col_spec.name}")
    else:
        lines.append(f"Optional — {col_spec.name}")

    lines.append(f"Type: {_human_kind(col_spec.kind)}")
    if col_spec.enum_values:
        lines.append("Allowed values:")
        for v in col_spec.enum_values:
            lines.append(f"  • {v}")
    if col_spec.max_len is not None:
        lines.append(f"Max length: {col_spec.max_len} characters")
    if col_spec.note:
        lines.append("")
        lines.append(col_spec.note)

    # openpyxl Comment.width / .height are in points. ~260x140 fits ~7 lines.
    comment = Comment("\n".join(lines), author="Scout")
    comment.width = 280
    comment.height = max(120, 18 * (len(lines) + 1))
    return comment


def _human_kind(kind: str) -> str:
    """Convert the internal ColumnKind to something a human reading the
    cell-comment will recognize."""
    return {
        "text": "Text",
        "long_text": "Text (long-form, multi-line OK)",
        "int": "Whole number",
        "float": "Decimal number",
        "bool": "TRUE or FALSE",
        "date": "Date (YYYY-MM-DD)",
        "uuid": "UUID — leave blank on new rows",
        "list_text": "List of text, semicolon-separated (e.g. 'A; B; C')",
        "list_uuid": "List of UUIDs, semicolon-separated",
        "enum": "Pick one from the dropdown",
        "action": "upsert / delete / skip",
    }.get(kind, kind)


def _write_sample_row(ws: Worksheet, spec: SheetSpec) -> None:
    sample = _SAMPLE_ROWS.get(spec.name)
    if not sample:
        return
    ordered = [sample.get(c.name, "") for c in spec.columns]
    ws.append(ordered)

    # Style the sample row distinctively + comment the first cell.
    sample_row = ws.max_row
    for col_idx in range(1, len(spec.columns) + 1):
        cell = ws.cell(row=sample_row, column=col_idx)
        cell.fill = _SAMPLE_FILL
        cell.font = _SAMPLE_FONT
        cell.alignment = Alignment(vertical="top", wrap_text=True)

    first_data_cell = ws.cell(row=sample_row, column=1)
    first_data_cell.comment = Comment(
        "This is a sample row. Replace it with real data, or leave it — "
        "the importer skips any row whose primary name starts with "
        "'Sample —' so you don't have to remember to delete it.",
        author="Scout",
    )


def _attach_validation(ws: Worksheet, spec: SheetSpec) -> None:
    """Add Excel/Google-Sheets data validation for enum and bool columns."""
    for col_idx, col_spec in enumerate(spec.columns, start=1):
        if col_spec.enum_values:
            values = list(col_spec.enum_values)
        elif col_spec.kind == "bool":
            values = ["TRUE", "FALSE"]
        else:
            continue

        # Quote values so commas inside any value don't break the formula.
        formula = '"' + ",".join(values) + '"'
        dv = DataValidation(
            type="list",
            formula1=formula,
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Invalid value",
            error=f"Pick one of: {', '.join(values)}",
        )
        col_letter = get_column_letter(col_idx)
        # Cover rows 2-1000 so the dropdown works as the user adds rows.
        dv.add(f"{col_letter}2:{col_letter}1000")
        ws.add_data_validation(dv)


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
        "team": "team",
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
        "description": "Example series row; replace or delete.",
        "typical_month": 9,
        "typical_topics": "fictitious; sample",
        "homepage": "https://example.invalid",
        "is_active": "TRUE",
    },
}


def _set_column_widths(ws: Worksheet, spec: SheetSpec) -> None:
    """Starting widths so the template opens cleanly in Sheets."""
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
        "role_seniority": 16,
        "location_country": 16,
        "location_city": 20,
        "linkedin_url": 36,
        "github_url": 36,
        "website_url": 36,
        "homepage": 36,
        "slug": 22,
        "typical_month": 14,
        "is_active": 12,
        "pending_review": 16,
        "display_order": 16,
    }
    for idx, col in enumerate(spec.columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = widths.get(col.name, 22)
