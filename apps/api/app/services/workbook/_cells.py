"""Per-cell value parsing + formatting (plan 31).

Pure functions; no Pydantic, no DB. Each parse_X returns either the
typed value or raises ``CellError`` so callers can build per-row error
lists. format_X is the inverse: takes a Python value, returns the
cell-display string.

Formula-injection defense: every cell starting with `=`, `+`, `-`, `@`
is prefixed with `'` on export and rejected on import.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True, frozen=True)
class CellError(ValueError):
    field: str
    value: Any
    message: str

    def __str__(self) -> str:  # type: ignore[override]
        return f"{self.field}: {self.message}"


FORMULA_LEADS = ("=", "+", "-", "@")


# ---------------------------------------------------------------------------
# Top-level guards
# ---------------------------------------------------------------------------
def is_formula_leading(s: str) -> bool:
    return bool(s) and s[0] in FORMULA_LEADS


def coerce_str(value: Any) -> str | None:
    """Convert raw openpyxl cell value to a stripped string, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        out = value.strip()
        return out or None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        # Avoid scientific notation creeping in for large ints.
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10] if isinstance(value, date) else value.isoformat()
    return str(value).strip() or None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_text(field: str, raw: Any, *, required: bool, max_len: int | None) -> str | None:
    s = coerce_str(raw)
    if s is None:
        if required:
            raise CellError(field, raw, "required; cell is empty")
        return None
    if is_formula_leading(s):
        raise CellError(
            field,
            raw,
            "value starts with =/+/-/@ (formula-like); refuse on import. "
            "Prefix with an apostrophe on the sheet.",
        )
    if max_len is not None and len(s) > max_len:
        raise CellError(field, raw, f"too long (>{max_len} chars)")
    return s


def parse_long_text(field: str, raw: Any, *, required: bool) -> str | None:
    return parse_text(field, raw, required=required, max_len=None)


def parse_int(field: str, raw: Any, *, required: bool) -> int | None:
    if raw is None or raw == "":
        if required:
            raise CellError(field, raw, "required; cell is empty")
        return None
    try:
        if isinstance(raw, bool):  # bool is int in Python; reject explicitly
            raise ValueError
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise CellError(field, raw, "not an integer") from exc


def parse_bool(field: str, raw: Any, *, required: bool) -> bool | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise CellError(field, raw, "required; cell is empty")
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in {"true", "t", "yes", "y", "1"}:
        return True
    if s in {"false", "f", "no", "n", "0"}:
        return False
    raise CellError(field, raw, "not TRUE / FALSE (case-insensitive)")


def parse_uuid(field: str, raw: Any, *, required: bool) -> UUID | None:
    s = coerce_str(raw)
    if s is None:
        if required:
            raise CellError(field, raw, "required; cell is empty")
        return None
    try:
        return UUID(s)
    except ValueError as exc:
        raise CellError(field, raw, "not a valid UUID") from exc


def parse_list_text(field: str, raw: Any, *, required: bool) -> list[str]:
    s = coerce_str(raw)
    if s is None:
        if required:
            raise CellError(field, raw, "required; cell is empty")
        return []
    if is_formula_leading(s):
        raise CellError(field, raw, "value starts with =/+/-/@ (formula-like); refuse on import.")
    items = [p.strip() for p in s.split(";")]
    return [i for i in items if i]


def parse_date(field: str, raw: Any, *, required: bool) -> date | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise CellError(field, raw, "required; cell is empty")
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    s = str(raw).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError as exc:
        raise CellError(field, raw, "not YYYY-MM-DD") from exc


def parse_enum(field: str, raw: Any, *, required: bool, allowed: tuple[str, ...]) -> str | None:
    s = coerce_str(raw)
    if s is None:
        if required:
            raise CellError(field, raw, "required; cell is empty")
        return None
    if s not in allowed:
        raise CellError(field, raw, f"not in allowed set {sorted(allowed)}")
    return s


def parse_action(field: str, raw: Any) -> str:
    """Synthetic _action column. Defaults to 'upsert' when blank."""
    s = coerce_str(raw)
    if s is None or s == "":
        return "upsert"
    s = s.lower()
    if s not in {"upsert", "delete", "skip"}:
        raise CellError(field, raw, "must be one of upsert / delete / skip")
    return s


# ---------------------------------------------------------------------------
# Formatters (writer.py uses these)
# ---------------------------------------------------------------------------
def fmt_str(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    # Defuse formula-leading content on EXPORT by prefixing an apostrophe.
    # On re-import the parser strips it.
    if is_formula_leading(s):
        return "'" + s
    return s


def fmt_list_text(value: list[str] | None) -> str:
    if not value:
        return ""
    return "; ".join(str(v) for v in value if v is not None)


def fmt_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "TRUE" if value else "FALSE"


def fmt_uuid(value: UUID | str | None) -> str:
    if value is None:
        return ""
    return str(value)


def fmt_int(value: int | None) -> str:
    return "" if value is None else str(value)


def fmt_date(value: date | None) -> str:
    return "" if value is None else value.isoformat()
