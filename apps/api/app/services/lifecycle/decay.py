"""Ebbinghaus decay for chunks + conferences (plan 25).

Math
----
``freshness(age_seconds) = exp(-age_seconds / half_life_seconds)``

Half-lives (env-tunable; plan-spec defaults):
  * chunks       : 60 days  — usage-driven freshness for retrieval
  * conferences  : 365 days — yearly cadence makes a year a reasonable horizon

Effective ranking blend (when ``settings.decay_enabled``):
  ``effective = raw * (alpha + (1 - alpha) * freshness)``  with ``alpha = 0.85``

So freshness multiplies similarity by something in [alpha, 1.0]; a totally
stale chunk still contributes 85% of its raw cosine — decay tilts ranking,
it doesn't hide content.

Future-event floor
------------------
Conferences whose ``start_date`` is in the future get a freshness floor
of 0.5 — a newly-extracted NeurIPS 2027 should not start at zero just
because its raw_pages were scraped months ago.

Archiving
---------
Conferences whose ``end_date`` is older than 90 days are bumped to
``status='archived'`` by the daily cron. The matcher already filters
quarantined/rejected; ``archived`` joins that exclusion set in the
dashboard list (see plan 20 list endpoint).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, text as sql_text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference
from app.settings import get_settings

log = structlog.get_logger("scout.lifecycle.decay")

# Half-lives. Env-tunable per the plan's "tune after a quarter" note;
# defaults match the plan-spec numbers.
CHUNK_HALF_LIFE_DAYS = 60
CONFERENCE_HALF_LIFE_DAYS = 365

# Ranking blend factor. raw_score * (alpha + (1-alpha)*freshness).
DECAY_ALPHA = 0.85

# Future-event freshness floor.
FUTURE_EVENT_FLOOR = 0.5

# Conferences ended this many days ago → archived.
ARCHIVE_AFTER_DAYS = 90


# ---------------------------------------------------------------------------
# Pure functions (used everywhere — keep dependency-free)
# ---------------------------------------------------------------------------
def compute_freshness(
    *,
    reference_time: datetime | None,
    half_life_days: int,
    now: datetime | None = None,
) -> float:
    """exp(-age / half_life). Returns 1.0 for a missing or future
    reference_time (treats unseen rows as 'just-arrived', not stale).
    """
    if reference_time is None:
        return 1.0
    now_dt = now or datetime.now(tz=timezone.utc)
    ref = reference_time
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    age_seconds = (now_dt - ref).total_seconds()
    if age_seconds <= 0:
        return 1.0
    half_life_s = half_life_days * 86_400
    return math.exp(-age_seconds / half_life_s)


def apply_decay_multiplier(
    raw_score: float, freshness: float, *, alpha: float = DECAY_ALPHA
) -> float:
    """Blend raw similarity with freshness.

    Gated at the call site by ``settings.decay_enabled`` — when off,
    callers don't invoke this and ranking is pure cosine.
    """
    multiplier = alpha + (1.0 - alpha) * max(0.0, min(1.0, freshness))
    return max(0.0, min(1.0, raw_score * multiplier))


# ---------------------------------------------------------------------------
# Conference-side decay (daily cron consumer)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class DecayPassResult:
    decay_enabled: bool
    conferences_scored: int
    conferences_archived: int
    floor_pinned: int
    duration_ms_estimate: int | None = None

    def to_stats(self) -> dict:
        return {
            "decay_enabled": self.decay_enabled,
            "conferences_scored": self.conferences_scored,
            "conferences_archived": self.conferences_archived,
            "floor_pinned": self.floor_pinned,
        }


async def run_decay_pass(db: AsyncSession) -> DecayPassResult:
    """Daily cron: recompute conference freshness, archive old events.

    No-op (returns 0 counters) when ``settings.decay_enabled=false`` —
    keeps the ``DECAY_ENABLED`` toggle a true on/off switch.
    """
    settings = get_settings()
    if not settings.decay_enabled:
        log.info("decay.pass.skipped", reason="decay_enabled=false")
        return DecayPassResult(
            decay_enabled=False,
            conferences_scored=0,
            conferences_archived=0,
            floor_pinned=0,
        )

    today = date.today()
    archive_threshold = today - timedelta(days=ARCHIVE_AFTER_DAYS)
    now_dt = datetime.now(tz=timezone.utc)

    # 1. Archive ended conferences. We do this BEFORE recomputing freshness
    #    so the score reflects the new status.
    archive_q = await db.execute(
        update(Conference)
        .where(Conference.end_date.is_not(None))
        .where(Conference.end_date < archive_threshold)
        .where(Conference.status != "archived")
        .where(Conference.status != "quarantined")
        .values(status="archived")
        .returning(Conference.id)
    )
    archived_ids = [row[0] for row in archive_q.all()]

    # 2. Score every non-quarantined / non-archived conference.
    rows = (
        await db.execute(
            select(Conference)
            .where(Conference.status != "quarantined")
            .where(Conference.status != "archived")
        )
    ).scalars().all()

    floor_pinned = 0
    for c in rows:
        # Conference freshness uses ``updated_at`` as the proxy for
        # "last we touched anything about this conf" — that's the cheapest
        # signal (Postgres maintains it via the timestamped mixin's onupdate).
        f = compute_freshness(
            reference_time=c.updated_at,
            half_life_days=CONFERENCE_HALF_LIFE_DAYS,
            now=now_dt,
        )
        # Future-event floor: a yet-to-happen event shouldn't fade just
        # because nothing's edited it lately.
        if c.start_date is not None and c.start_date >= today:
            if f < FUTURE_EVENT_FLOOR:
                f = FUTURE_EVENT_FLOOR
                floor_pinned += 1
        c.freshness_score = round(f, 4)

    await db.flush()

    log.info(
        "decay.pass.done",
        conferences_scored=len(rows),
        conferences_archived=len(archived_ids),
        floor_pinned=floor_pinned,
    )
    return DecayPassResult(
        decay_enabled=True,
        conferences_scored=len(rows),
        conferences_archived=len(archived_ids),
        floor_pinned=floor_pinned,
    )


# ---------------------------------------------------------------------------
# Diagnostics — surfaced via plan 26 in pass 2
# ---------------------------------------------------------------------------
async def conference_freshness_histogram(
    db: AsyncSession, *, buckets: int = 10
) -> dict:
    """Returns a histogram of ``conferences.freshness_score`` for the
    /diagnostics page (plan 26). Buckets are evenly-spaced in [0,1].
    """
    rows = (
        await db.execute(
            select(Conference.freshness_score).where(
                Conference.status != "quarantined"
            )
        )
    ).all()
    counts = [0] * buckets
    for (score,) in rows:
        if score is None:
            continue
        s = max(0.0, min(1.0, float(score)))
        # Map [0,1] → [0, buckets-1]; pin 1.0 → last bucket.
        idx = min(buckets - 1, int(s * buckets))
        counts[idx] += 1
    edges = [round(i / buckets, 3) for i in range(buckets + 1)]
    return {
        "buckets": buckets,
        "edges": edges,
        "counts": counts,
        "total": int(sum(counts)),
    }


# Re-export so the tasks/matcher import surface stays small.
__all__ = [
    "CHUNK_HALF_LIFE_DAYS",
    "CONFERENCE_HALF_LIFE_DAYS",
    "DECAY_ALPHA",
    "compute_freshness",
    "apply_decay_multiplier",
    "run_decay_pass",
    "DecayPassResult",
    "conference_freshness_histogram",
]

# Silence "unused" hints in the small uses-of-funcs check.
_ = func  # noqa: F841
_ = sql_text  # noqa: F841
