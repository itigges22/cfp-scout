"""CFP-closing digest builder (plan 24).

Daily 09:00 cron walks every active conference's ``cfp_deadlines`` array,
explodes it to one row per deadline, filters to the next 30 days, buckets
by window (0-7 / 8-14 / 15-30 days), ranks each bucket by overall match
score, caps at 10 per bucket, and writes one ``app.notifications`` row of
kind ``cfp_digest``.

Idempotent within a calendar day: re-running marks any prior un-seen
``cfp_digest`` rows as ``seen=true`` before inserting the new one, so the
bell badge stays at 1 instead of N.

We don't send email/Slack from the app — copy-to-clipboard from the UI
covers Phase 1's "post the digest somewhere" need without dragging in
credentials / SMTP / OAuth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, Sme
from app.db.models.matching import Match
from app.db.models.ops import Notification
from app.services.matcher import ALGORITHM_VERSION

log = structlog.get_logger("scout.digest.cfp")

# Status set that qualifies for the digest — anything in the human-review
# pipeline plus approved. Rejected/quarantined/low_messaging_fit are
# excluded because the operator's decision was "don't act on this".
_ELIGIBLE_STATUSES: frozenset[str] = frozenset(
    [
        "discovered",
        "needs_review",
        "needs_review_pillar",
        "needs_sme_review",
        "approved",
    ]
)

# Bucket boundaries (days from today, inclusive).
BUCKET_BOUNDS = [(0, 7, "0_7"), (8, 14, "8_14"), (15, 30, "15_30")]

# Cap per bucket. Plan-tunable env override left for the env layer; the
# default is in the plan's spec.
MAX_PER_BUCKET = 10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class DigestEntry:
    """One (conference, deadline) row inside a bucket."""

    conference_id: str
    name: str
    slug: str
    status: str
    overall_score: float | None
    deadline_kind: str           # "submission" / "abstract" / "workshop" / ...
    deadline_date: str           # ISO
    days_until: int
    top_sme_id: str | None
    top_sme_name: str | None
    website: str | None
    location: str | None         # "city, country" or "virtual" or None


@dataclass(slots=True)
class DigestResult:
    generated_at: str
    notification_id: str | None
    buckets: dict[str, list[DigestEntry]] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)

    def to_payload(self) -> dict:
        """Shape persisted into ``notifications.payload``."""
        return {
            "generated_at": self.generated_at,
            "buckets": {
                k: [asdict(e) for e in v] for k, v in self.buckets.items()
            },
            "stats": self.stats,
        }

    def to_stats(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "notification_id": self.notification_id,
            "n_entries_total": sum(self.stats.values()),
            "by_bucket": self.stats,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
async def build_cfp_digest(
    db: AsyncSession, *, today: date | None = None
) -> DigestResult:
    """Walk the conference + cfp_deadlines space, bucket, persist, return.

    Caller commits. Marks any prior un-seen `cfp_digest` notifications as
    `seen=true` before inserting the new one — bell stays at 1.
    """
    today = today or date.today()
    horizon = today + timedelta(days=30)

    # Pull conferences + matches in one join. We only need rows whose
    # status is eligible AND whose JSONB cfp_deadlines array is non-empty.
    # The JSONB check via ``func.jsonb_array_length(... ) > 0`` is
    # cheap with an expression index, but for phase-1 volume we can just
    # filter in Python — much simpler code, same result.
    rows = (
        await db.execute(
            select(Conference, Match)
            .outerjoin(
                Match,
                (Match.conference_id == Conference.id)
                & (Match.algorithm_version == ALGORITHM_VERSION),
            )
            .where(Conference.status.in_(list(_ELIGIBLE_STATUSES)))
        )
    ).all()

    # Pre-fetch SME names for the "top SME" hint. We map top_sme_id =
    # the first recommended_sme_id from the match row (matcher already
    # sorted them by composite score).
    sme_ids: set[UUID] = set()
    for _, m in rows:
        if m and m.recommended_sme_ids:
            sme_ids.add(m.recommended_sme_ids[0])
    sme_name_by_id: dict[UUID, str] = {}
    if sme_ids:
        sme_rows = (
            await db.execute(
                select(Sme.id, Sme.full_name).where(Sme.id.in_(list(sme_ids)))
            )
        ).all()
        sme_name_by_id = {sid: name for sid, name in sme_rows}

    # Build entries: explode (conf, deadlines_array) into per-deadline rows.
    entries: list[DigestEntry] = []
    for conf, match in rows:
        deadlines = list(conf.cfp_deadlines or [])
        if not deadlines:
            continue
        top_sme_id = (
            match.recommended_sme_ids[0]
            if (match and match.recommended_sme_ids)
            else None
        )
        top_sme_name = (
            sme_name_by_id.get(top_sme_id) if top_sme_id is not None else None
        )
        for d in deadlines:
            iso = d.get("deadline_date")
            if not iso:
                continue
            try:
                dd = date.fromisoformat(iso)
            except (TypeError, ValueError):
                continue
            if not (today <= dd <= horizon):
                continue
            entries.append(
                DigestEntry(
                    conference_id=str(conf.id),
                    name=conf.name,
                    slug=conf.slug,
                    status=conf.status,
                    overall_score=(
                        float(match.overall_score) if match else None
                    ),
                    deadline_kind=d.get("kind") or "other",
                    deadline_date=iso,
                    days_until=(dd - today).days,
                    top_sme_id=str(top_sme_id) if top_sme_id else None,
                    top_sme_name=top_sme_name,
                    website=conf.website,
                    location=_pretty_location(conf),
                )
            )

    # Bucket + rank.
    buckets: dict[str, list[DigestEntry]] = {key: [] for _, _, key in BUCKET_BOUNDS}
    for e in entries:
        for lo, hi, key in BUCKET_BOUNDS:
            if lo <= e.days_until <= hi:
                buckets[key].append(e)
                break
    for key in buckets:
        buckets[key].sort(
            key=lambda e: (
                -(e.overall_score or 0.0),  # higher score first
                e.deadline_date,            # then earlier deadline first
            )
        )
        buckets[key] = buckets[key][:MAX_PER_BUCKET]

    stats = {key: len(buckets[key]) for key in buckets}
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    # Mark prior un-seen digests as seen so the bell doesn't accumulate.
    await db.execute(
        update(Notification)
        .where(Notification.kind == "cfp_digest")
        .where(Notification.seen.is_(False))
        .values(seen=True)
    )

    result = DigestResult(
        generated_at=generated_at,
        notification_id=None,
        buckets=buckets,
        stats=stats,
    )
    # Persist as a fresh unread notification only if there's something to
    # surface; an empty digest doesn't need a bell badge.
    total = sum(stats.values())
    if total > 0:
        row = Notification(kind="cfp_digest", payload=result.to_payload(), seen=False)
        db.add(row)
        await db.flush()
        await db.refresh(row)
        result.notification_id = str(row.id)

    log.info(
        "digest.cfp.built",
        total_entries=total,
        bucket_0_7=stats.get("0_7", 0),
        bucket_8_14=stats.get("8_14", 0),
        bucket_15_30=stats.get("15_30", 0),
        notification_id=result.notification_id,
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pretty_location(c: Conference) -> str | None:
    if c.is_virtual:
        return "virtual"
    parts = [p for p in (c.location_city, c.location_country) if p]
    return ", ".join(parts) if parts else None


def to_markdown(result: DigestResult, *, today: date | None = None) -> str:
    """Format the digest as Markdown for the UI's copy-to-clipboard button.

    Pure function (no DB), so the frontend can also call this shape from a
    persisted notification.payload via the API if it wants server-rendered
    copy.
    """
    today = today or date.today()
    out: list[str] = [f"# Scout CFP Digest — {today.isoformat()}", ""]
    titles = {
        "0_7": "Closing this week (0-7 days)",
        "8_14": "Closing next week (8-14 days)",
        "15_30": "Closing this month (15-30 days)",
    }
    any_content = False
    for _, _, key in BUCKET_BOUNDS:
        entries = result.buckets.get(key, [])
        if not entries:
            continue
        any_content = True
        out.append(f"## {titles[key]}")
        out.append("")
        for e in entries:
            score = (
                f" (score {int(round((e.overall_score or 0) * 100))})"
                if e.overall_score is not None
                else ""
            )
            sme = (
                f"; suggested SME: {e.top_sme_name}"
                if e.top_sme_name
                else ""
            )
            kind_label = e.deadline_kind.replace("_", " ").title()
            out.append(
                f"- **{e.name}**{score} — {kind_label} closes {e.deadline_date}"
                f"{sme}"
            )
        out.append("")
    if not any_content:
        out.append("_No CFPs closing in the next 30 days._")
    return "\n".join(out).rstrip() + "\n"


def to_entries_for_api(result: DigestResult) -> dict:
    """Shape used by the GET endpoints when a notification is fresh enough
    to render directly (without re-reading from notifications.payload)."""
    return result.to_payload()
