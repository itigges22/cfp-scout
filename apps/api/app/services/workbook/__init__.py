"""XLSX workbook import/export (plan 31).

The team collaborates on a single XLSX in Google Sheets, then uploads it
to Scout. Round-trip-stable: export → edit → re-import is a no-op when no
edits are made.

Pass-1 sheet coverage:
  * Pillars
  * Industries (controlled vocabulary; held in-memory + validated against
    audience inputs)
  * Audiences
  * SMEs
  * Topics
  * Series

Pass-2 sheet coverage:
  * Messaging (structured-source-only; PDF source still uploaded via /uploads/pdf)
  * PastConferences (mirrors the plan-9 CSV import)
"""

from app.services.workbook.apply import apply_diff
from app.services.workbook.diff import DiffResult, compute_diff
from app.services.workbook.reader import ParsedWorkbook, parse_workbook
from app.services.workbook.template import build_empty_template
from app.services.workbook.writer import build_current_state_workbook

__all__ = [
    "ParsedWorkbook",
    "parse_workbook",
    "build_empty_template",
    "build_current_state_workbook",
    "DiffResult",
    "compute_diff",
    "apply_diff",
]
