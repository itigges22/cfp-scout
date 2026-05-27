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

# Whole-word token Jaccard threshold — covers the case where one name
# is a short prefix of the other (e.g. past "KubeCon" → upcoming
# "KubeCon Conference 2027"), which fails trigram because the longer
# string has many trigrams the short one doesn't share. Token Jaccard
# is more forgiving here because it operates at the word level.
_TOKEN_JACCARD_THRESHOLD = 0.5


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


def _tokens(s: str) -> set[str]:
    """Whole-word tokens from a normalized name. Single-letter tokens
    are dropped because they're usually noise (the "&" in
    "KubeCon & CloudNativeCon" becoming a stray "a")."""
    return {tok for tok in s.split() if len(tok) > 1}


def _token_jaccard(a: str, b: str) -> float:
    """Token-level Jaccard. Handles the prefix case where one name is
    a strict subset of the other ("kubecon" tokens ⊂ "kubecon
    conference" tokens), which trigram Jaccard penalizes because of
    the length asymmetry in the denominator."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _names_match(target: str, past: str) -> bool:
    """Decide whether two normalized event names are the same series.

    Three independent signals — match wins if ANY fires:

      1. Trigram Jaccard ≥ 0.45 — catches "vLLM Meetup - Mumbai" vs
         "vLLM Meetup - Istanbul" (different city tail, shared stem).
      2. Token Jaccard ≥ 0.50 — catches "KubeCon" vs "KubeCon
         Conference 2027" (one is a strict subset of the other at
         the word level).
      3. Whole-name substring containment — catches the asymmetric
         case where one normalized name is literally a substring of
         the other after year/edition strip. Cheap belt-and-braces
         against the long-name-vs-short-name false negative.
    """
    if not target or not past:
        return False
    if _similarity(target, past) >= _SIMILARITY_THRESHOLD:
        return True
    if _token_jaccard(target, past) >= _TOKEN_JACCARD_THRESHOLD:
        return True
    # Substring containment with a word-boundary check — "kube" in
    # "kubernetes" should NOT match, but "kubecon" in "kubecon
    # conference" should. Enforce by requiring the shorter side to
    # be at least one full token.
    shorter, longer = (target, past) if len(target) <= len(past) else (past, target)
    if " " + shorter + " " in " " + longer + " ":
        return True
    return False


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
    """Return True when any past-attended name passes ``_names_match``
    against ``conference_name``. See ``_names_match`` for the full
    matching policy — trigram OR token OR substring."""
    if not conference_name or not attended_names:
        return False
    target = _normalize(conference_name)
    if not target:
        return False
    return any(_names_match(target, past) for past in attended_names)


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
