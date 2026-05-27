"""Match upcoming conferences against the operator's past-attendance history.

Why this exists: the operator imports a CSV of past events their team
attended (Complete=TRUE rows in the calendar sync → ``app.past_conferences``).
We want to surface "you attended this series before" on the upcoming
conference list so the operator can tell at a glance whether something
is a returning vs first-time event.

The hard problem: ``past_conferences.series_id`` is typically NULL
(the calendar-sync import doesn't auto-link to series), so we can't
just JOIN on series_id. Instead we match by **normalized name** —
strip the year + edition tokens from both sides and compare. Cheap,
deterministic, no LLM. Lossy at the edges ("KubeCon" vs "KubeCon +
CloudNativeCon" won't match) but catches the obvious cases.

Used by:
  - ``GET /api/v1/conferences`` to populate the ``previously_attended``
    field on each row + filter via ``?attendance_filter=new|returning``.
  - The Stage-D-adjacent ``series_memory`` boost to lift conferences
    whose past edition was actually attended (vs just approved in
    Scout's decisions table).
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, PastConference
from app.services.series.detector import strip_year_and_edition

log = structlog.get_logger("scout.past_attendance")

# Trigram-similarity threshold for "same series" matching. Picked
# empirically:
#   "vLLM Meetup - Mumbai"  vs  "vLLM Meetup - Istanbul"  → 0.55+
#   "KubeCon + CloudNativeCon Europe" vs "KubeCon + CloudNativeCon NA" → 0.60+
#   "Devoxx Morocco" vs "Devoxx France" → 0.45
#   "Conf42 LLMs"   vs  "KubeCon EU"    → 0.10
# 0.45 sits below the obvious matches and well above the cross-event
# noise floor.
_SIMILARITY_THRESHOLD = 0.45


def _normalize(name: str) -> str:
    """Lowercase + strip year/edition + strip non-alphanumeric.
    Use this as the canonical form for trigram comparison.
    """
    s = strip_year_and_edition(name or "").lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _trigrams(s: str) -> set[str]:
    padded = f"  {s}  "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity of trigram sets, in [0, 1]. Matches the
    pattern used by series.detector — close enough to pg_trgm at
    this scale and lets us match in Python without a DB roundtrip
    per comparison."""
    if not a or not b:
        return 0.0
    ga, gb = _trigrams(a), _trigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


async def load_attended_names(db: AsyncSession) -> tuple[str, ...]:
    """Return normalized names of past conferences the operator
    actually attended (attended_sme_ids non-empty).

    Tuple (not set) because consumers do trigram comparison, not
    exact lookup. ~30 strings; cheap to hold in memory per request.
    """
    rows = (
        await db.execute(
            select(PastConference.name)
            .where(PastConference.attended_sme_ids != [])
        )
    ).scalars().all()
    return tuple(_normalize(n) for n in rows if n and n.strip())


def is_previously_attended(conference_name: str, attended_names: tuple[str, ...]) -> bool:
    """Return True when any past-attended name shares enough trigrams
    with ``conference_name`` to count as the same conference series.

    Uses trigram Jaccard ≥ ``_SIMILARITY_THRESHOLD``. This catches:
      - exact series matches across cities ("vLLM Meetup - Mumbai"
        attended → "vLLM Meetup - Istanbul" upcoming)
      - exact series matches across years ("ODSC East 2024" attended
        → "ODSC East 2026" upcoming)
      - close but not identical names where the operator clearly
        means the same event
    """
    if not conference_name or not attended_names:
        return False
    target = _normalize(conference_name)
    if not target:
        return False
    for name in attended_names:
        if _similarity(target, name) >= _SIMILARITY_THRESHOLD:
            return True
    return False


async def conference_was_previously_attended(
    db: AsyncSession, conference: Conference
) -> bool:
    """Single-conference convenience — used by the matcher's boost
    pipeline where we don't want to load the full set."""
    return is_previously_attended(
        conference.name or "", await load_attended_names(db)
    )


__all__ = [
    "conference_was_previously_attended",
    "is_previously_attended",
    "load_attended_name_set",
]
