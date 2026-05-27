"""Post-matcher score adjustments based on business logic, not embeddings.

The four-stage matcher (messaging / pillar / SME / judge) measures
semantic relevance — does this conference match what the operator
cares about? It doesn't measure actionability — *when* the operator
can act on it, or whether they've already shown an affinity for this
event series.

This module applies three additive boosts to ``overall_score`` after
the matcher stages have produced it:

- **CFP urgency** — events with a CFP deadline in the next 30 days
  get a +0.10 boost. Catches the failure mode where a perfect
  semantic match is buried at rank 40 because more-relevant events
  outrank it, even though those events don't have an open CFP yet.
- **Recency penalty** — events whose start date is more than 12
  months out get a small (-0.05) penalty. You can't realistically
  plan that far ahead, so they're less actionable today.
- **Series memory** — if the operator approved any past edition of
  the same conference series, future editions in that series get
  a +0.10 boost. Pure recall of stated preferences.

Each boost is toggleable via settings so an operator can turn off
the temporal / preference signal and rank purely on semantic fit.

All three boosts are intentionally small (+/- 0.10 max). They nudge
the ranking — they don't override it. A genuinely-irrelevant event
with an open CFP still ranks below an obvious match without one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference
from app.db.models.matching import Decision

log = structlog.get_logger("scout.matcher.boosts")

# Boost magnitudes — kept small so semantic fit dominates.
CFP_URGENCY_BOOST = 0.10
RECENCY_PENALTY = -0.05
FLAGSHIP_EVENT_BOOST = 0.15

# Series-memory boost is signed by the operator's verdict on the
# past edition they attended. Symmetric +/-0.10 for explicit
# verdicts; a smaller +0.05 for "we attended but haven't decided
# yet" (default `unsure`).
SERIES_MEMORY_BOOST_POSITIVE = 0.10
SERIES_MEMORY_BOOST_NEUTRAL = 0.05
SERIES_MEMORY_BOOST_NEGATIVE = -0.10
# Kept for backwards-compat with code that imports the old name.
SERIES_MEMORY_BOOST = SERIES_MEMORY_BOOST_POSITIVE

# Threshold windows.
CFP_URGENCY_DAYS = 30
RECENCY_PENALTY_MONTHS = 12  # events further out than this get the penalty

# Flagship INDUSTRY / DEVELOPER conferences that a commercial
# open-source software vendor (Red Hat, etc.) should default to
# being present at. A future-dated edition whose name matches any
# of these gets a +0.15 bump.
#
# Deliberately INDUSTRY-only:
#   - Where developers + platform engineers + IT decision-makers go.
#   - Where vendors speak, sponsor booths, and generate leads.
#
# Deliberately EXCLUDES pure academic ML venues (NeurIPS, ICLR,
# ICML, AAAI, EMNLP, ACL, CVPR). Those are great events but their
# audience is researchers / PhD students / professors — wrong
# audience for a commercial-software-vendor go-to-market motion.
# Academic-hybrid venues like KDD and RecSys have meaningful
# industry presence but still trend academic; treated as mid-tier
# (no flagship boost) and the judge prompt explicitly calibrates
# them as "adjacent" for commercial vendors.
#
# Match is case-insensitive substring on conference.name. List
# updated periodically; submit additions via a docs PR.
_FLAGSHIP_PATTERNS: tuple[str, ...] = (
    # GPU + inference / model serving
    "nvidia gtc",
    "ray summit",
    # Kubernetes / cloud-native + Linux Foundation events
    "kubecon",
    "cloudnativecon",
    "open source summit",
    "openinfra summit",
    "linux foundation",
    "kubeflow",
    "dockercon",
    # Frameworks (industry-facing)
    "pytorch conference",
    # AI / ML practitioner conferences
    "ai engineer world fair",
    "ai engineer summit",
    "ai infra summit",
    "ai infrastructure summit",
    "mlops world",
    "mlops community",
    "cloud native ai",
    "open data science conference",  # ODSC — practitioner-oriented
    # Major cloud + enterprise platform conferences
    "aws re:invent",
    "google cloud next",
    "microsoft ignite",
    "microsoft build",
    "data + ai summit",
    "databricks data + ai",
    "snowflake summit",
    # Developer + platform engineer events
    "github universe",
    "all things open",
    # NOTE: DevOpsDays was removed — the brand is well-known but
    # individual city editions are 50-200 person community meetups,
    # not flagship-scale. They land in the matcher's regular tier
    # via the messaging/judge stages just fine.
    # World-class industry AI summits
    "world summit ai",
    "transform x",
)

# Override the flagship boost when the conference name contains any
# of these substrings — they indicate a community-satellite spinoff
# of a flagship brand, not the main event itself. Microsoft Build
# proper is a 5000-person Seattle conference; "Microsoft Build //
# Localhost:Capetown" is a 50-person community watch party. We
# want the boost on the former and not the latter.
_FLAGSHIP_EXCLUSIONS: tuple[str, ...] = (
    "//localhost",
    ": localhost",
    " localhost",
    "community edition",
    " watch party",
    "viewing party",
)


@dataclass(frozen=True, slots=True)
class BoostContext:
    """Pre-loaded state needed to compute boosts WITHOUT additional
    DB queries per conference. Built once at the start of a list
    request and reused across all conferences in the page.

    Keeps the conference-list endpoint at O(1) DB queries regardless
    of how many conferences are rendered.
    """

    # Normalized past-conference name → verdict. Built from
    # past_conferences where attended_sme_ids is non-empty.
    attended_name_to_verdict: dict[str, str]
    # Set of conference series the operator approved in app.decisions.
    approved_series_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class BoostBreakdown:
    """What got applied + why. The matcher logs this for observability
    so an operator can see why a conference's overall_score doesn't
    exactly equal the weighted blend of the stage scores."""

    cfp_urgency: float = 0.0
    recency_penalty: float = 0.0
    series_memory: float = 0.0
    flagship_event: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.cfp_urgency
            + self.recency_penalty
            + self.series_memory
            + self.flagship_event
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "cfp_urgency": self.cfp_urgency,
            "recency_penalty": self.recency_penalty,
            "series_memory": self.series_memory,
            "flagship_event": self.flagship_event,
            "total": self.total,
        }


async def compute_boosts(
    *,
    db: AsyncSession,
    conference: Conference,
    settings,
    context: BoostContext | None = None,
) -> BoostBreakdown:
    """Compute the additive boost for one conference. Each component
    respects its own enable-flag setting; disabled components return
    0.0 so the resulting total is just the sum of what's enabled.

    If ``context`` is provided, ``_series_memory`` uses it for zero
    additional DB queries. Otherwise we load context just-in-time
    (one query) — convenient for single-conference detail endpoints
    that don't justify the batching overhead.
    """
    today = datetime.now(tz=UTC).date()

    cfp = _cfp_urgency(conference, today) if settings.enable_cfp_urgency_boost else 0.0
    recency = _recency_penalty(conference, today) if settings.enable_recency_penalty else 0.0
    series: float
    if settings.enable_series_memory_boost:
        ctx = context if context is not None else await load_boost_context(db)
        series = _series_memory_from_ctx(conference, ctx)
    else:
        series = 0.0
    flagship = (
        _flagship_event(conference, today)
        if settings.enable_flagship_event_boost
        else 0.0
    )
    return BoostBreakdown(
        cfp_urgency=cfp,
        recency_penalty=recency,
        series_memory=series,
        flagship_event=flagship,
    )


async def load_boost_context(db: AsyncSession) -> BoostContext:
    """One-shot loader for the data ``_series_memory`` needs.

    Two cheap queries (one for past_conferences + verdicts, one for
    series_ids touched by approved decisions). Hold the result for
    the duration of one API request — operator edits during a render
    don't matter; the next request picks up the fresh state.
    """
    from app.db.models.entities import PastConference
    from app.services.past_attendance import _normalize

    past_rows = (
        await db.execute(
            select(PastConference.name, PastConference.verdict)
            .where(PastConference.attended_sme_ids != [])
        )
    ).all()
    attended: dict[str, str] = {}
    for name, verdict in past_rows:
        if not name or not name.strip():
            continue
        key = _normalize(name)
        if not key:
            continue
        # Last-write-wins on duplicate normalized names. Operator can
        # always re-thumb the duplicate row if they care which wins.
        attended[key] = verdict

    approved_q = (
        select(Conference.series_id)
        .join(Decision, Decision.conference_id == Conference.id)
        .where(Decision.decision == "approved")
        .where(Conference.series_id.is_not(None))
        .distinct()
    )
    approved_ids = frozenset(
        sid for sid in (await db.execute(approved_q)).scalars().all() if sid is not None
    )
    return BoostContext(
        attended_name_to_verdict=attended,
        approved_series_ids=approved_ids,
    )


def _cfp_urgency(conference: Conference, today: date) -> float:
    """CFP closes in the next 30 days → +0.10. Past deadlines and
    deadlines further than 30 days out → 0.0."""
    deadline = conference.cfp_close_at
    if deadline is None:
        return 0.0
    days_to_deadline = (deadline - today).days
    if 0 <= days_to_deadline <= CFP_URGENCY_DAYS:
        return CFP_URGENCY_BOOST
    return 0.0


def _recency_penalty(conference: Conference, today: date) -> float:
    """Events more than 12 months in the future → -0.05.

    Past events (already happened) return 0.0 — they're handled by
    the archive/status pipeline elsewhere, not by this boost.
    """
    start = conference.start_date
    if start is None or start < today:
        return 0.0
    horizon = today + timedelta(days=30 * RECENCY_PENALTY_MONTHS)
    if start > horizon:
        return RECENCY_PENALTY
    return 0.0


def _flagship_event(conference: Conference, today: date) -> float:
    """+0.15 if the conference's name matches a known flagship event
    pattern AND the event is in the future AND the name doesn't
    contain a community-satellite exclusion marker.

    Past-dated flagships (NeurIPS 2024 etc.) are correctly handled
    elsewhere — they get archived / aged out. The boost only applies
    to upcoming editions because that's where strategic value lives.

    Match is case-insensitive substring on the conference name —
    cheap, deterministic, no LLM, no DB lookup. The pattern list
    is curated and vendor-neutral (see ``_FLAGSHIP_PATTERNS``); the
    exclusion list catches community-satellite spinoffs that share
    the flagship's brand name but are 50-person local meetups, not
    the actual flagship event (see ``_FLAGSHIP_EXCLUSIONS``).
    """
    if not conference.name:
        return 0.0
    if conference.start_date and conference.start_date < today:
        return 0.0
    name_lower = conference.name.lower()
    # Community-satellite exclusions short-circuit before pattern
    # matching — even if "microsoft build" matches, a name containing
    # "//localhost" is the Cape Town community edition, not the
    # actual Microsoft Build flagship.
    for exclusion in _FLAGSHIP_EXCLUSIONS:
        if exclusion in name_lower:
            return 0.0
    for pattern in _FLAGSHIP_PATTERNS:
        if pattern in name_lower:
            return FLAGSHIP_EVENT_BOOST
    return 0.0


def _series_memory_from_ctx(conference: Conference, ctx: BoostContext) -> float:
    """Verdict-signed series-memory boost using pre-loaded context.

    Three signals, in priority order:

      1. Past attendance with EXPLICIT verdict:
         - ``would_attend`` → +0.10 (clear positive)
         - ``would_not_attend`` → −0.10 (clear penalty — keep these
           events OFF the top of the list even though we did go)
      2. Past attendance with ``unsure`` verdict:
         - +0.05 (we attended once; small positive while the operator
           hasn't formed an opinion)
      3. Approved past edition in decisions table (no attendance row):
         - +0.10

    Operator intent (verdict) always wins over implicit signals when
    a verdict exists.
    """
    # Path (1+2): past attendance with verdict — use trigram-style
    # match against the pre-normalized name set.
    target_name = conference.name or ""
    if target_name and ctx.attended_name_to_verdict:
        # Local import to avoid circular dep through past_attendance.
        from app.services.past_attendance import _normalize, _similarity

        target_norm = _normalize(target_name)
        if target_norm:
            best_verdict: str | None = None
            best_sim = 0.0
            for past_name, verdict in ctx.attended_name_to_verdict.items():
                sim = _similarity(target_norm, past_name)
                if sim > best_sim:
                    best_sim = sim
                    best_verdict = verdict
            if best_verdict is not None and best_sim >= 0.45:
                if best_verdict == "would_attend":
                    return SERIES_MEMORY_BOOST_POSITIVE
                if best_verdict == "would_not_attend":
                    return SERIES_MEMORY_BOOST_NEGATIVE
                # "unsure" — small positive while operator decides.
                return SERIES_MEMORY_BOOST_NEUTRAL

    # Path (3): approved past edition by series_id linkage.
    if conference.series_id is not None and conference.series_id in ctx.approved_series_ids:
        return SERIES_MEMORY_BOOST_POSITIVE
    return 0.0


async def _series_memory(db: AsyncSession, conference: Conference) -> float:
    """Single-conference wrapper for legacy callers (matcher pipeline,
    detail endpoints). Loads context on the fly. Prefer the batched
    ``_series_memory_from_ctx`` for list endpoints."""
    ctx = await load_boost_context(db)
    return _series_memory_from_ctx(conference, ctx)


def apply_boosts(base_score: float, boosts: BoostBreakdown) -> float:
    """Add the boost total to ``base_score``, clamping to [0, 1]."""
    return max(0.0, min(1.0, base_score + boosts.total))


__all__ = [
    "BoostBreakdown",
    "BoostContext",
    "apply_boosts",
    "compute_boosts",
    "load_boost_context",
    "CFP_URGENCY_BOOST",
    "RECENCY_PENALTY",
    "SERIES_MEMORY_BOOST",
    "SERIES_MEMORY_BOOST_POSITIVE",
    "SERIES_MEMORY_BOOST_NEUTRAL",
    "SERIES_MEMORY_BOOST_NEGATIVE",
    "FLAGSHIP_EVENT_BOOST",
]
