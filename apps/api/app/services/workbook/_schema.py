"""Per-sheet column definitions (plan 31).

One ``SheetSpec`` per supported sheet. The reader, writer, diff, apply,
and template generator all consume the same spec — single source of truth
for column names, types, and required-ness so adding a sheet means
defining its spec once.

Conventions baked into the spec:
  * ``_scout_id`` is always the first column — round-trip identifier.
  * ``_action`` is always the second column — `upsert` (default) /
    `delete` / `skip`.
  * Boolean cells: ``TRUE`` / ``FALSE`` (case-insensitive on read).
  * Array cells (``kind=list_text``): semicolon-separated, no trailing
    `;`, whitespace stripped.
  * Date cells: ISO ``YYYY-MM-DD``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ColumnKind = Literal[
    "text",
    "long_text",  # text but typically multi-line; same parse, different col-width hint
    "int",
    "float",
    "bool",
    "date",
    "uuid",
    "list_text",  # semicolon-separated
    "list_uuid",  # semicolon-separated UUIDs (for SME → topic / audience FK arrays)
    "enum",  # arbitrary string from a fixed set
    "action",  # the synthetic _action column
]


@dataclass(slots=True, frozen=True)
class ColumnSpec:
    """Column inside a sheet."""

    name: str
    kind: ColumnKind
    required: bool = False
    # Per-kind extras. ``enum_values`` for kind=enum; ``max_len`` for kind=text.
    enum_values: tuple[str, ...] = ()
    max_len: int | None = None
    note: str | None = None  # surfaced into the Reference sheet


@dataclass(slots=True, frozen=True)
class SheetSpec:
    """Top-level sheet description."""

    name: str  # tab name in the workbook
    entity: str  # short label used in audit_log + diff stats
    description: str
    columns: tuple[ColumnSpec, ...]

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


# ---------------------------------------------------------------------------
# Shared columns (always come first; identical across every sheet)
# ---------------------------------------------------------------------------
_ID_COL = ColumnSpec(
    "_scout_id",
    "uuid",
    required=False,
    note="Round-trip identifier. Leave blank on insert; preserved on export.",
)
_ACTION_COL = ColumnSpec(
    "_action",
    "action",
    required=False,
    enum_values=("upsert", "delete", "skip"),
    note="upsert (default) / delete / skip. delete is soft (is_active=false).",
)


# ---------------------------------------------------------------------------
# Sheet specs
# ---------------------------------------------------------------------------
PILLARS = SheetSpec(
    name="Pillars",
    entity="strategic_pillar",
    description="the four-pillar strategy. Edit order via display_order.",
    columns=(
        _ID_COL,
        _ACTION_COL,
        ColumnSpec("name", "text", required=True, max_len=80, note="Pillar canonical name."),
        ColumnSpec("description", "long_text", required=True, note="What this pillar covers."),
        ColumnSpec(
            "display_order", "int", required=True, note="Order in the dashboard pillar list (1-N)."
        ),
    ),
)

INDUSTRIES = SheetSpec(
    name="Industries",
    entity="industry",
    description=(
        "Controlled vocabulary for audience_profiles.industry. Adding an "
        "industry here lets it pass the audience validator."
    ),
    columns=(
        _ID_COL,  # unused (no DB row), kept for shape symmetry
        _ACTION_COL,
        ColumnSpec("name", "text", required=True, max_len=80, note="Industry label."),
    ),
)

AUDIENCES = SheetSpec(
    name="Audiences",
    entity="audience_profile",
    description="Audience profiles. Plan 5's Pydantic guardrails are enforced on import.",
    columns=(
        _ID_COL,
        _ACTION_COL,
        ColumnSpec("name", "text", required=True, max_len=80),
        ColumnSpec(
            "industry", "text", required=True, max_len=80, note="Must match an Industries entry."
        ),
        ColumnSpec(
            "role_seniority",
            "enum",
            required=True,
            enum_values=("executive", "director", "manager", "ic", "mixed"),
        ),
        ColumnSpec("description", "long_text", required=True, note="50-500 chars."),
        ColumnSpec("primary_pain_points", "list_text", required=True, note="Semicolon-separated."),
        ColumnSpec("key_messages", "list_text", required=True, note="Semicolon-separated."),
        ColumnSpec("exclusion_criteria", "list_text", note="Semicolon-separated; optional."),
        ColumnSpec("is_active", "bool", note="TRUE (default) / FALSE."),
    ),
)

SMES = SheetSpec(
    name="SMEs",
    entity="sme",
    description="Subject-matter experts. primary_topics + audience_focus reference Topics + Audiences by name.",
    columns=(
        _ID_COL,
        _ACTION_COL,
        ColumnSpec("full_name", "text", required=True, max_len=100),
        ColumnSpec("email", "text", max_len=200),
        ColumnSpec("team", "text", required=True, max_len=60, note="e.g. team, Platform, Edge."),
        ColumnSpec(
            "expertise_areas", "list_text", required=True, note="Semicolon-separated; 1-12 items."
        ),
        ColumnSpec(
            "primary_topics",
            "list_text",
            required=False,
            note="Semicolon-separated Topic NAMES (not UUIDs). Resolved on import; unknown topics → error.",
        ),
        ColumnSpec(
            "audience_focus",
            "list_text",
            required=False,
            note="Semicolon-separated Audience NAMES. Resolved on import.",
        ),
        ColumnSpec(
            "location_country", "text", required=True, max_len=2, note="ISO-3166-1 alpha-2."
        ),
        ColumnSpec("location_city", "text", max_len=100),
        ColumnSpec("bio", "long_text", required=True, note="200-2000 chars."),
        ColumnSpec("linkedin_url", "text", max_len=300, note="external_links.linkedin"),
        ColumnSpec("github_url", "text", max_len=300, note="external_links.github"),
        ColumnSpec("website_url", "text", max_len=300, note="external_links.website"),
        ColumnSpec("is_active", "bool", note="TRUE (default) / FALSE."),
    ),
)

TOPICS = SheetSpec(
    name="Topics",
    entity="topic",
    description="Controlled topic vocabulary. Adding a row here promotes the topic to active immediately.",
    columns=(
        _ID_COL,
        _ACTION_COL,
        ColumnSpec("name", "text", required=True, max_len=60),
        ColumnSpec("slug", "text", max_len=80, note="Auto-derived from name if blank."),
        ColumnSpec(
            "aliases",
            "list_text",
            note="Semicolon-separated alternate names matched by extraction.",
        ),
        ColumnSpec("is_active", "bool", note="TRUE (default) / FALSE."),
        ColumnSpec(
            "pending_review", "bool", note="TRUE leaves the topic out of matching. Default FALSE."
        ),
    ),
)

SERIES = SheetSpec(
    name="Series",
    entity="conference_series",
    description="Known year-over-year conference series. Powers the past-attendance bonus + the detector.",
    columns=(
        _ID_COL,
        _ACTION_COL,
        ColumnSpec("canonical_name", "text", required=True, max_len=150),
        ColumnSpec(
            "aliases",
            "list_text",
            note="Semicolon-separated; e.g. NIPS;Neural Information Processing Systems.",
        ),
        ColumnSpec("description", "long_text", note="One-line summary for the settings UI."),
        ColumnSpec("typical_month", "int", note="1-12; the usual month of the year."),
        ColumnSpec(
            "typical_topics", "list_text", note="Semicolon-separated; bootstrap hints for matching."
        ),
        ColumnSpec("homepage", "text", max_len=500),
        ColumnSpec("is_active", "bool", note="TRUE (default) / FALSE."),
    ),
)


# Sheets in the canonical order they appear in the workbook. Reference is
# the first sheet but generated by template.py rather than from a SheetSpec.
SHEET_SPECS: tuple[SheetSpec, ...] = (
    PILLARS,
    INDUSTRIES,
    AUDIENCES,
    SMES,
    TOPICS,
    SERIES,
)
SHEETS_BY_NAME: dict[str, SheetSpec] = {s.name: s for s in SHEET_SPECS}
