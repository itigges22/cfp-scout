"""Structured context injection for the agent (post-plan-22 fix).

RAG is great at "what does X say" but terrible at "give me all rows
matching Y" and "rank Z by Z." This module fills that gap by pre-fetching
structured DB results based on simple intent detection on the question,
then injecting those results as authoritative context blocks alongside
the regular RAG snippets.

The agent's prompt is updated to treat structured blocks as authoritative
complete lists — when the user asks "all conferences in Europe", the
LLM enumerates every row in the structured block rather than just the
6-16 that happened to make the RAG cut.

Intent detection is deliberately rule-based (keyword matching). No
extra LLM round trip, no model overhead. Easy to extend by adding to the
keyword sets below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Iterable

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, Sme
from app.db.models.matching import Match
from app.services.matcher import ALGORITHM_VERSION

log = structlog.get_logger("scout.agent.structured_context")


class Intent(str, Enum):
    LIST_CONFERENCES = "list_conferences"
    FILTER_BY_LOCATION = "filter_by_location"
    RECOMMEND_SMES = "recommend_smes"
    UPCOMING_CFP = "upcoming_cfp"
    UPCOMING_EVENTS = "upcoming_events"


@dataclass(slots=True)
class StructuredBlock:
    """One pre-fetched context block.

    `kind` is a short identifier the prompt uses to introduce the block.
    `title` is a human-readable header. `rows` is the actual table content
    rendered as plain text lines (one per row) so the LLM doesn't have to
    parse JSON.
    """

    kind: str
    title: str
    rows: list[str]
    note: str | None = None

    def to_prompt_string(self) -> str:
        out = [f"### {self.title}"]
        if self.note:
            out.append(f"_({self.note})_")
        if not self.rows:
            out.append("(no rows matched)")
        else:
            out.extend(self.rows)
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Region → ISO-3166-1 alpha-2 code expansion
# ---------------------------------------------------------------------------
EUROPE_CODES = {
    "GB", "IE", "FR", "DE", "ES", "PT", "IT", "NL", "BE", "LU", "CH",
    "AT", "DK", "SE", "NO", "FI", "IS", "PL", "CZ", "SK", "HU", "RO",
    "BG", "GR", "RS", "HR", "SI", "EE", "LV", "LT", "UA", "BY", "AL",
    "MK", "TR",
}
NORTH_AMERICA_CODES = {"US", "CA", "MX"}
SOUTH_AMERICA_CODES = {"BR", "AR", "CL", "CO", "PE", "UY", "VE", "EC", "BO", "PY"}
ASIA_CODES = {
    "CN", "JP", "KR", "IN", "SG", "HK", "TW", "TH", "VN", "ID", "MY",
    "PH", "BD", "PK", "NP", "LK", "KZ",
}
MIDDLE_EAST_CODES = {"IL", "TR", "AE", "SA", "QA", "KW", "JO", "LB", "IR"}
AFRICA_CODES = {"ZA", "EG", "MA", "TN", "KE", "NG", "GH", "CM", "ET", "CI"}
OCEANIA_CODES = {"AU", "NZ"}
LATAM_CODES = SOUTH_AMERICA_CODES | {"MX"} | {"PR", "DO", "CR", "GT"}

REGION_ALIASES: dict[str, set[str]] = {
    "europe": EUROPE_CODES,
    "european": EUROPE_CODES,
    "eu": EUROPE_CODES,
    "north america": NORTH_AMERICA_CODES,
    "na": NORTH_AMERICA_CODES,
    "south america": SOUTH_AMERICA_CODES,
    "latam": LATAM_CODES,
    "latin america": LATAM_CODES,
    "asia": ASIA_CODES,
    "apac": ASIA_CODES,
    "asia pacific": ASIA_CODES | OCEANIA_CODES,
    "middle east": MIDDLE_EAST_CODES,
    "africa": AFRICA_CODES,
    "oceania": OCEANIA_CODES,
    "australia": {"AU"},
    "nz": {"NZ"},
    # Common country mentions resolve to their ISO code too.
    "usa": {"US"},
    "united states": {"US"},
    "us": {"US"},
    "uk": {"GB"},
    "united kingdom": {"GB"},
    "germany": {"DE"},
    "france": {"FR"},
    "japan": {"JP"},
    "china": {"CN"},
    "india": {"IN"},
    "brazil": {"BR"},
    "canada": {"CA"},
    "spain": {"ES"},
    "italy": {"IT"},
}


def _extract_location_codes(question: str) -> set[str]:
    """Return ISO-3166-1 alpha-2 codes implied by the question's
    geography mentions. Longest match first so 'north america' beats 'na'.
    """
    q = " " + question.lower() + " "
    out: set[str] = set()
    for alias in sorted(REGION_ALIASES, key=len, reverse=True):
        if f" {alias} " in q or f" {alias}," in q or f" {alias}." in q:
            out |= REGION_ALIASES[alias]
    return out


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------
_KEYWORDS_LIST = {
    "list", "all", "show me", "show all", "which", "what conferences",
    "what events",
}
_KEYWORDS_SMES = {
    "who", "send", "sme", "smes", "speaker", "team", "attendee",
    "best person", "recommend",
}
_KEYWORDS_CFP = {
    "cfp", "deadline", "closing", "close", "submit", "submission",
    "due", "ends",
}
_KEYWORDS_UPCOMING = {
    "upcoming", "next", "this month", "this quarter", "soon",
    "coming up", "approved",
}


def detect_intents(question: str) -> set[Intent]:
    q = " " + question.lower() + " "
    intents: set[Intent] = set()
    if any(kw in q for kw in _KEYWORDS_LIST):
        intents.add(Intent.LIST_CONFERENCES)
    if any(kw in q for kw in _KEYWORDS_SMES):
        intents.add(Intent.RECOMMEND_SMES)
    if any(kw in q for kw in _KEYWORDS_CFP):
        intents.add(Intent.UPCOMING_CFP)
    if any(kw in q for kw in _KEYWORDS_UPCOMING):
        intents.add(Intent.UPCOMING_EVENTS)
    if _extract_location_codes(question):
        intents.add(Intent.FILTER_BY_LOCATION)
    # "conferences" mentioned with no other intent still implies a list.
    if "conference" in q or "event" in q:
        intents.add(Intent.LIST_CONFERENCES)
    return intents


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------
async def fetch_structured_blocks(
    db: AsyncSession,
    *,
    question: str,
    max_rows: int = 25,
) -> list[StructuredBlock]:
    """Return the structured context blocks relevant to the question.

    Order matters — earlier blocks are more visible to the LLM. Conferences
    come first (the question almost always grounds in those), then SMEs if
    a who-to-send intent fires, then CFP closings if asked.
    """
    intents = detect_intents(question)
    location_codes = _extract_location_codes(question) if Intent.FILTER_BY_LOCATION in intents else set()
    blocks: list[StructuredBlock] = []

    today = date.today()
    soon = today + timedelta(days=90)

    # Build a candidate-conferences query that respects detected filters.
    stmt = (
        select(Conference)
        .where(Conference.status.not_in(["quarantined", "rejected"]))
        .order_by(desc(Conference.confidence_score))
    )
    if location_codes:
        stmt = stmt.where(Conference.location_country.in_(list(location_codes)))
    if Intent.UPCOMING_EVENTS in intents:
        stmt = stmt.where(Conference.start_date.is_not(None))
        stmt = stmt.where(Conference.start_date.between(today, soon))
    if Intent.UPCOMING_CFP in intents:
        stmt = stmt.where(Conference.cfp_close_at.is_not(None))
        stmt = stmt.where(Conference.cfp_close_at.between(today, today + timedelta(days=60)))

    stmt = stmt.limit(max_rows)
    confs = (await db.execute(stmt)).scalars().all()

    if Intent.LIST_CONFERENCES in intents or Intent.FILTER_BY_LOCATION in intents or Intent.UPCOMING_EVENTS in intents:
        rows = [_format_conference_row(c) for c in confs]
        title = "Conferences matching the query"
        filters: list[str] = []
        if location_codes:
            filters.append(f"location in {sorted(location_codes)}")
        if Intent.UPCOMING_EVENTS in intents:
            filters.append(f"start_date in next 90 days (≤ {soon.isoformat()})")
        if Intent.UPCOMING_CFP in intents:
            filters.append("CFP closes in next 60 days")
        note = "; ".join(filters) if filters else "no location/date filter — top by confidence"
        blocks.append(
            StructuredBlock(
                kind="conferences_matching",
                title=title,
                rows=rows,
                note=f"{len(rows)} of {len(confs)} matches · {note}",
            )
        )

    # SME recommendations: top SMEs by composite score across the matched
    # conferences. If no conferences matched, fall back to the global top
    # SMEs by recent match composite.
    if Intent.RECOMMEND_SMES in intents:
        sme_rows = await _top_smes_for_conferences(db, confs, limit=15)
        blocks.append(
            StructuredBlock(
                kind="sme_recommendations",
                title="Top SMEs by matcher composite score",
                rows=sme_rows,
                note=(
                    f"across {len(confs)} matched conferences"
                    if confs
                    else "global top across all recent matches"
                ),
            )
        )

    # CFP closing soon — handy roll-up regardless of intent if the user
    # explicitly mentioned deadlines.
    if Intent.UPCOMING_CFP in intents:
        cfp_rows = await _cfp_closing_rows(db, location_codes, limit=20)
        blocks.append(
            StructuredBlock(
                kind="cfp_closing",
                title="CFP deadlines in the next 60 days",
                rows=cfp_rows,
                note=(
                    f"filtered to {sorted(location_codes)}"
                    if location_codes
                    else "no location filter"
                ),
            )
        )

    log.info(
        "agent.structured_context",
        intents=[i.value for i in intents],
        location_codes=sorted(location_codes),
        n_blocks=len(blocks),
        n_conferences=len(confs),
    )
    return blocks


def _format_conference_row(c: Conference) -> str:
    """Compact per-conference row. Skipping UUIDs (the LLM doesn't need them
    in its reply) keeps the prompt + response token counts manageable
    when listing 25 conferences."""
    where = c.location_city or ""
    if c.location_country:
        where = f"{where}, {c.location_country}" if where else c.location_country
    if c.is_virtual:
        where = "Virtual"
    when = c.start_date.isoformat() if c.start_date else "TBD"
    cfp = f" · CFP: {c.cfp_close_at.isoformat()}" if c.cfp_close_at else ""
    return f"- **{c.name}** · {when} · {where or '?'}{cfp}"


async def _top_smes_for_conferences(
    db: AsyncSession, confs: list[Conference], *, limit: int
) -> list[str]:
    """Per-conference SME recommendations.

    The matcher persists ``Match.recommended_sme_ids`` as an ordered UUID
    array (best-fit first by composite, no per-SME composite stored on
    the row — that's computed live by /conferences/{id}/smes). For the
    structured-context block we surface the top-3 SMEs per conference
    so a "who to send to each event" query gets a real, complete answer.

    Falls back to global top-recommended across all recent matches when
    no conferences match the location filter.
    """
    if not confs:
        recent_matches = (
            await db.execute(
                select(Match)
                .where(Match.algorithm_version == ALGORITHM_VERSION)
                .order_by(desc(Match.computed_at))
                .limit(min(50, max(10, limit)))
            )
        ).scalars().all()
        conf_name_by_id: dict[str, str] = {}
        if recent_matches:
            cids = [m.conference_id for m in recent_matches]
            crows = (
                await db.execute(select(Conference.id, Conference.name).where(Conference.id.in_(cids)))
            ).all()
            conf_name_by_id = {str(r.id): r.name for r in crows}
    else:
        conf_ids = [c.id for c in confs]
        recent_matches = (
            await db.execute(
                select(Match)
                .where(Match.algorithm_version == ALGORITHM_VERSION)
                .where(Match.conference_id.in_(conf_ids))
            )
        ).scalars().all()
        conf_name_by_id = {str(c.id): c.name for c in confs}

    if not recent_matches:
        return []

    # Collect every SME UUID referenced as a recommendation so we can
    # resolve names in one batched query.
    all_sme_ids: set[str] = set()
    for m in recent_matches:
        for sid in (m.recommended_sme_ids or [])[:3]:
            all_sme_ids.add(str(sid))
    if not all_sme_ids:
        return []
    sme_rows = (
        await db.execute(
            select(Sme.id, Sme.full_name, Sme.team).where(Sme.id.in_(list(all_sme_ids)))
        )
    ).all()
    name_by_id = {str(r.id): (r.full_name, r.team) for r in sme_rows}

    out: list[str] = []
    # Order matches by overall_score descending so the most-relevant
    # conferences are surfaced first.
    recent_matches.sort(key=lambda m: m.overall_score or 0, reverse=True)
    for m in recent_matches[:limit]:
        cname = conf_name_by_id.get(str(m.conference_id), str(m.conference_id))
        top = (m.recommended_sme_ids or [])[:3]
        if not top:
            continue
        sme_strs = []
        for sid in top:
            full_name, team = name_by_id.get(str(sid), ("?", "?"))
            sme_strs.append(f"{full_name} ({team})")
        score_pct = round((m.overall_score or 0) * 100)
        out.append(
            f"- **{cname}** (overall fit {score_pct}/100) → "
            f"{', '.join(sme_strs)}"
        )
    return out


async def _cfp_closing_rows(
    db: AsyncSession, location_codes: set[str], *, limit: int
) -> list[str]:
    today = date.today()
    cutoff = today + timedelta(days=60)
    stmt = (
        select(Conference)
        .where(Conference.cfp_close_at.is_not(None))
        .where(Conference.cfp_close_at.between(today, cutoff))
        .where(Conference.status.not_in(["quarantined", "rejected"]))
        .order_by(Conference.cfp_close_at)
        .limit(limit)
    )
    if location_codes:
        stmt = stmt.where(Conference.location_country.in_(list(location_codes)))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        f"- **{c.name}** · CFP closes {c.cfp_close_at.isoformat()} · "
        f"{c.location_city or '?'}, {c.location_country or '?'} · id: {c.id}"
        for c in rows
    ]
