"""Map linted calendar-sync events to Scout's DB rows.

Linted events have the AI BU Developer Marketing shape (event name, dates,
city/country, Complete flag, attendees as comma-separated names). We
project that into:

  - Complete=TRUE rows → `app.past_conferences` (year derived from
    start_date; attendees resolved against Sme.full_name).

  - Complete=FALSE rows → `app.conferences` (the team plans to attend
    these; status="approved" since the team has already committed).

The orchestrator in __init__.py drives this end-to-end and returns a
preview-or-apply result that the endpoint surfaces as JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, PastConference, Sme
from app.services.calendar_sync.linter import LintedEvent, split_attendees
from app.services.extraction.dedup import build_slug, find_duplicate, year_for

log = structlog.get_logger("scout.calendar_sync.mapper")

PAST_ROLE_DEFAULT = "attendee"  # PastConference.role default when CSV doesn't specify
PAST_SESSION_TYPE = None  # Not in the calendar-sync shape; leave null
IMPORTED_FROM_TAG = "calendar_sync_import"


@dataclass(slots=True)
class RowDecision:
    """Per-row outcome from the mapper. The endpoint surfaces a list of
    these so the operator can preview-then-apply."""

    source_row: int  # original CSV row number (2-based)
    target: str  # "past_conference" | "conference" | "skipped"
    action: str  # "insert" | "update" | "skip"
    name: str
    summary: str  # one-line human description used in the preview UI
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MapResult:
    decisions: list[RowDecision]
    inserted_past: int = 0
    inserted_conferences: int = 0
    updated_past: int = 0
    updated_conferences: int = 0
    skipped: int = 0
    unknown_attendees: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "inserted_past": self.inserted_past,
            "inserted_conferences": self.inserted_conferences,
            "updated_past": self.updated_past,
            "updated_conferences": self.updated_conferences,
            "skipped": self.skipped,
            "unknown_attendees": sorted(set(self.unknown_attendees)),
            "decisions": [
                {
                    "source_row": d.source_row,
                    "target": d.target,
                    "action": d.action,
                    "name": d.name,
                    "summary": d.summary,
                    "warnings": d.warnings,
                }
                for d in self.decisions
            ],
        }


async def map_events(
    db: AsyncSession,
    events: Sequence[LintedEvent],
    *,
    apply: bool,
    actor_label: str = IMPORTED_FROM_TAG,
) -> MapResult:
    """Resolve attendees, decide per-row what to do, and (when apply=True)
    persist. Caller commits.

    apply=False is preview mode: every decision is computed and returned
    without any DB writes — that's what the /preview-import endpoint uses.
    """
    # Batch-resolve all attendee names that appear in the CSV (avoids one
    # SELECT per row).
    all_names = sorted({n.lower() for ev in events for n in split_attendees(ev.attendees_raw)})
    name_to_id: dict[str, UUID] = {}
    if all_names:
        rows = (
            await db.execute(
                select(Sme.id, Sme.full_name).where(
                    Sme.is_active.is_(True),
                )
            )
        ).all()
        name_to_id = {full_name.strip().lower(): _id for _id, full_name in rows}

    result = MapResult(decisions=[])

    for ev in events:
        warnings = list(ev.warnings)

        attendee_names = split_attendees(ev.attendees_raw)
        resolved: list[UUID] = []
        unknown: list[str] = []
        for n in attendee_names:
            sme_id = name_to_id.get(n.lower())
            if sme_id is None:
                unknown.append(n)
            else:
                resolved.append(sme_id)
        if unknown:
            warnings.append(
                f"unmatched attendee names: {unknown} — skipped in attendee list"
            )
            result.unknown_attendees.extend(unknown)

        if ev.complete:
            decision = await _map_past_conference(
                db,
                ev,
                resolved_attendees=resolved,
                unresolved_attendees=unknown,
                warnings=warnings,
                apply=apply,
                actor_label=actor_label,
            )
            if apply and decision.action == "insert":
                result.inserted_past += 1
            elif apply and decision.action == "update":
                result.updated_past += 1
        else:
            decision = await _map_conference(
                db,
                ev,
                warnings=warnings,
                apply=apply,
                actor_label=actor_label,
            )
            if apply and decision.action == "insert":
                result.inserted_conferences += 1
            elif apply and decision.action == "update":
                result.updated_conferences += 1

        if decision.action == "skip":
            result.skipped += 1
        result.decisions.append(decision)

    return result


async def _map_past_conference(
    db: AsyncSession,
    ev: LintedEvent,
    *,
    resolved_attendees: list[UUID],
    unresolved_attendees: list[str],
    warnings: list[str],
    apply: bool,
    actor_label: str,
) -> RowDecision:
    year = ev.start_date.year if ev.start_date else date.today().year

    # Look up existing past row by (lowercased name, year) — best-effort dedup.
    existing = (
        await db.execute(
            select(PastConference)
            .where(PastConference.year == year)
            .where(func_lower(PastConference.name) == ev.name.strip().lower())
        )
    ).scalar_one_or_none()

    # All attendee names from the CSV, whether they resolved or not —
    # stored verbatim so the row always answers "who was there?" even
    # when those people aren't SMEs yet.
    all_attendee_names = split_attendees(ev.attendees_raw)
    summary = (
        f"{ev.name} ({year}) · {ev.city}, {ev.country} · "
        f"{len(all_attendee_names)} attendee"
        f"{'' if len(all_attendee_names) == 1 else 's'} from CSV "
        f"({len(resolved_attendees)} linked to SMEs)"
    )
    # Surface the 0-match case so the operator knows to add SMEs + edit later.
    if not resolved_attendees and unresolved_attendees:
        warnings.append(
            "0 SMEs matched — raw attendee names captured in "
            "attended_by_names_raw. Add the SMEs on /smes, then edit "
            "this row to link them in."
        )

    if existing is None:
        if apply:
            row = PastConference(
                name=ev.name[:150],
                year=year,
                attended_sme_ids=resolved_attendees,
                attended_by_names_raw=all_attendee_names,
                role=PAST_ROLE_DEFAULT,
                session_type=PAST_SESSION_TYPE,
                notes=_build_notes(ev),
                imported_from=actor_label,
            )
            db.add(row)
        return RowDecision(
            source_row=ev.source_row,
            target="past_conference",
            action="insert",
            name=ev.name,
            summary=summary,
            warnings=warnings,
        )

    # Existing past_conference — refresh attendee links + raw names + notes.
    if apply:
        existing.attended_sme_ids = resolved_attendees or existing.attended_sme_ids
        # Always overwrite the raw names from the latest CSV — the source
        # spreadsheet is the source of truth for "who was there."
        existing.attended_by_names_raw = all_attendee_names
        new_notes = _build_notes(ev)
        if new_notes and new_notes != existing.notes:
            existing.notes = new_notes
        existing.imported_from = actor_label
    return RowDecision(
        source_row=ev.source_row,
        target="past_conference",
        action="update",
        name=ev.name,
        summary=summary,
        warnings=warnings,
    )


async def _map_conference(
    db: AsyncSession,
    ev: LintedEvent,
    *,
    warnings: list[str],
    apply: bool,
    actor_label: str,
) -> RowDecision:
    slug = build_slug(ev.name, year_for(ev.start_date.date() if ev.start_date else None))
    existing = await find_duplicate(db, slug=slug)
    summary = (
        f"{ev.name} · "
        f"{ev.start_date.strftime('%Y-%m-%d') if ev.start_date else 'TBD'} · "
        f"{ev.city}, {ev.country}"
    )

    if existing is None:
        if apply:
            row = Conference(
                name=ev.name[:200],
                slug=slug,
                start_date=ev.start_date.date() if ev.start_date else None,
                end_date=ev.end_date.date() if ev.end_date else None,
                location_city=ev.city[:120] if ev.city else None,
                location_country=(ev.country.upper()[:2] if ev.country else None),
                is_virtual=False,
                website=None,
                cfp_url=None,
                cfp_close_at=None,
                cfp_deadlines=[],
                cfp_topics_of_interest=[],
                topics=[ev.type] if ev.type else [],
                # The team has committed to attending these (Complete=FALSE
                # in their planning sheet), so jump straight to approved.
                status="approved",
                confidence_score=0.95,
            )
            db.add(row)
        return RowDecision(
            source_row=ev.source_row,
            target="conference",
            action="insert",
            name=ev.name,
            summary=summary,
            warnings=warnings,
        )

    # Existing conference — fill in any NULL fields without overwriting
    # human-curated values.
    if apply:
        if existing.start_date is None and ev.start_date:
            existing.start_date = ev.start_date.date()
        if existing.end_date is None and ev.end_date:
            existing.end_date = ev.end_date.date()
        if existing.location_city is None and ev.city:
            existing.location_city = ev.city[:120]
        if existing.location_country is None and ev.country:
            existing.location_country = ev.country.upper()[:2]
        if existing.status in ("discovered", "needs_review", "needs_review_pillar"):
            existing.status = "approved"
    return RowDecision(
        source_row=ev.source_row,
        target="conference",
        action="update",
        name=ev.name,
        summary=summary,
        warnings=warnings,
    )


def _build_notes(ev: LintedEvent) -> str:
    """Compose the notes string for a past_conferences row.

    Unmatched attendee names are NOT stuffed here anymore — they go into
    the structured `attended_by_names_raw` column. Notes is just the
    type / description / activities prose from the source row.
    """
    parts: list[str] = []
    if ev.type:
        parts.append(f"Type: {ev.type}")
    if ev.description:
        parts.append(ev.description)
    if ev.activities:
        parts.append(f"Activities: {ev.activities}")
    return "\n\n".join(parts)


# Convenience alias to keep the SQL ergonomic — sqlalchemy.func is verbose
# and we use it in one spot.
from sqlalchemy import func as _sa_func

func_lower = _sa_func.lower
