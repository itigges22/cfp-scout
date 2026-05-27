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
SERIES_MEMORY_BOOST = 0.10
FLAGSHIP_EVENT_BOOST = 0.15

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
) -> BoostBreakdown:
    """Compute the additive boost for one conference. Each component
    respects its own enable-flag setting; disabled components return
    0.0 so the resulting total is just the sum of what's enabled."""
    today = datetime.now(tz=UTC).date()

    cfp = _cfp_urgency(conference, today) if settings.enable_cfp_urgency_boost else 0.0
    recency = _recency_penalty(conference, today) if settings.enable_recency_penalty else 0.0
    series = (
        await _series_memory(db, conference)
        if settings.enable_series_memory_boost
        else 0.0
    )
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


async def _series_memory(db: AsyncSession, conference: Conference) -> float:
    """+0.10 boost when the operator has a real prior connection to
    this conference series — either:

      a) approved a past edition in Scout's decisions table (requires
         ``conference.series_id`` to be linked, plan 23), OR
      b) actually attended a past edition (any row in
         ``app.past_conferences`` whose normalized name matches and
         has non-empty ``attended_sme_ids``).

    Path (b) is the practical workhorse — most operators have past
    attendance imported from CSV but haven't built up a decision
    history in Scout yet. Path (a) is for once the operator's
    decision history accumulates.
    """
    # Path (a): approved past edition via series_id linkage.
    if conference.series_id is not None:
        approved_exists = (
            await db.execute(
                select(Decision.id)
                .join(Conference, Conference.id == Decision.conference_id)
                .where(Conference.series_id == conference.series_id)
                .where(Conference.id != conference.id)
                .where(Decision.decision == "approved")
                .limit(1)
            )
        ).scalar_one_or_none()
        if approved_exists is not None:
            return SERIES_MEMORY_BOOST

    # Path (b): operator actually attended a past edition. Local
    # import to avoid a circular dep through services/past_attendance.
    from app.services.past_attendance import conference_was_previously_attended

    if await conference_was_previously_attended(db, conference):
        return SERIES_MEMORY_BOOST
    return 0.0


def apply_boosts(base_score: float, boosts: BoostBreakdown) -> float:
    """Add the boost total to ``base_score``, clamping to [0, 1]."""
    return max(0.0, min(1.0, base_score + boosts.total))


__all__ = [
    "BoostBreakdown",
    "apply_boosts",
    "compute_boosts",
    "CFP_URGENCY_BOOST",
    "RECENCY_PENALTY",
    "SERIES_MEMORY_BOOST",
    "FLAGSHIP_EVENT_BOOST",
]
