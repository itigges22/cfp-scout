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


async def build_current_state_workbook(db: AsyncSession) -> bytes:
    """Build an XLSX populated with the current DB state.

    Uses the same formatting helpers as the empty template (rich README,
    cell comments on every column header, dropdown validation for enum
    columns, header colour by required/optional/system) — only the row
    contents differ: template ships sample rows + blank Settings values;
    this writer ships real DB rows + current Settings values.
    """
    # Import the shared formatting helpers from template.py so the export
    # and the template look identical in Sheets — only the data differs.
    from app.services.workbook.template import (
        _attach_validation,
        _build_readme_sheet,
        _set_column_widths,
        _write_header,
    )

    wb = Workbook()
    readme = wb.active
    readme.title = "README"
    _build_readme_sheet(readme)

    # Index of audience IDs → names + topic IDs → names so the SMEs sheet
    # can serialize references as human-readable names rather than UUIDs.
    audiences_by_id, topics_by_id = await _build_lookups(db)

    for spec in SHEET_SPECS:
        ws = wb.create_sheet(spec.name)
        _write_header(ws, spec)  # includes comments + colour-by-role
        rows = await _rows_for_sheet(db, spec, audiences_by_id, topics_by_id)
        for row in rows:
            ordered = [row.get(c.name, "") for c in spec.columns]
            ws.append(ordered)
        _attach_validation(ws, spec)  # dropdowns for enum + bool cols
        _set_column_widths(ws, spec)
        ws.sheet_view.showGridLines = True

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

    if spec.name == "Settings":
        return _settings_rows(populate_with_current=True)

    return []


def _settings_rows(*, populate_with_current: bool) -> list[dict]:
    """Build the Settings sheet rows.

    populate_with_current=True (used by export) writes the live settings
    values, including secrets unwrapped. populate_with_current=False (used
    by the template) leaves the `value` column blank so the operator
    fills it in.
    """
    # Local import — avoids a hard dependency on the api layer at module load.
    from pydantic import SecretStr

    from app.api.v1.admin_settings import SPECS as _SETTING_SPECS
    from app.settings import get_settings

    s = get_settings() if populate_with_current else None
    out: list[dict] = []
    for spec in _SETTING_SPECS:
        if populate_with_current and s is not None:
            raw = getattr(s, spec.name, None)
            if isinstance(raw, SecretStr):
                raw = raw.get_secret_value() or ""
            value_str = _format_setting_value(spec.kind, raw)
        else:
            value_str = ""
        out.append(
            {
                "name": spec.name,
                "value": value_str,
                "kind": spec.kind,
                "group": spec.group,
                "description": spec.description,
                "restart_required": "TRUE" if spec.restart_required else "FALSE",
                "is_secret": "TRUE" if spec.kind == "secret" else "FALSE",
            }
        )
    return out


def _format_setting_value(kind: str, raw) -> str:
    """Render a settings value for the workbook cell — list_str joins with
    `; `, bool emits TRUE/FALSE, secrets pass through (caller has already
    unwrapped SecretStr). None becomes empty string."""
    if raw is None:
        return ""
    if kind == "bool":
        return "TRUE" if bool(raw) else "FALSE"
    if kind == "list_str":
        if isinstance(raw, (list, tuple)):
            return "; ".join(str(x) for x in raw)
        return str(raw)
    return str(raw)


# ---------------------------------------------------------------------------
# Lookups + chrome
# ---------------------------------------------------------------------------
async def _build_lookups(db: AsyncSession) -> tuple[dict, dict]:
    auds = (await db.execute(select(AudienceProfile))).scalars().all()
    tops = (await db.execute(select(Topic))).scalars().all()
    return ({a.id: a for a in auds}, {t.id: t for t in tops})


# Header rendering, autosize, and the README sheet builder all live in
# template.py and are imported at call sites — see build_current_state_workbook.
