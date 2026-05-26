"""One-shot: recompute every conference's status from its current match scores.

After ADR-0008's judge stage rolled out, existing rows still had the
status that ``_choose_status`` produced before the judge column
existed — almost all were ``low_messaging_fit`` because the messaging
gate (default 0.55) is rarely cleared by the new properly-calibrated
scoring. This script walks every match row and re-applies the
current ``_choose_status`` logic (which now respects ``judge_score``
as a lift/veto signal) so the dashboard's "Needs review" / "Low
messaging fit" filters reflect the v2 matcher's actual verdict.

No LLM calls. Pure SQL + Python; runs in seconds.

Run inside the api container::

    podman cp scripts/refresh_statuses.py scout-api:/tmp/refresh_statuses.py
    podman exec scout-api /app/.venv/bin/python /tmp/refresh_statuses.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

from sqlalchemy import select, update

from app.db.models.entities import Conference
from app.db.models.matching import Match
from app.db.session import get_session_factory
from app.services import settings_overrides
from app.services.matcher.pipeline import ALGORITHM_VERSION, _choose_status
from app.settings import get_settings


async def main() -> int:
    factory = get_session_factory()
    async with factory() as db:
        await settings_overrides.load_from_db(db)
    get_settings.cache_clear()
    settings = get_settings()

    async with factory() as db:
        # Pull every conference + its current match row in one round-trip.
        rows = (
            await db.execute(
                select(
                    Conference.id,
                    Conference.name,
                    Conference.status,
                    Match.messaging_score,
                    Match.pillar_score,
                    Match.sme_score,
                    Match.judge_score,
                )
                .join(Match, Match.conference_id == Conference.id)
                .where(Match.algorithm_version == ALGORITHM_VERSION)
                .where(Conference.status != "quarantined")
                .where(Conference.status != "archived")
            )
        ).all()
    print(f"Refreshing status on {len(rows)} matched conferences.")

    before: Counter = Counter()
    after: Counter = Counter()
    transitions: Counter = Counter()
    changes: list[tuple[str, str, str]] = []

    async with factory() as db:
        for r in rows:
            new_status = _choose_status(
                ms_score=r.messaging_score,
                pl_score=r.pillar_score,
                sm_score=r.sme_score,
                judge_score=r.judge_score,
                settings=settings,
            )
            before[r.status] += 1
            after[new_status] += 1
            if new_status != r.status:
                transitions[(r.status, new_status)] += 1
                changes.append((r.name, r.status, new_status))
                await db.execute(
                    update(Conference)
                    .where(Conference.id == r.id)
                    .values(status=new_status)
                )
        await db.commit()

    def fmt(counter: Counter) -> str:
        return "  " + "\n  ".join(
            f"{k:<25} {v:>4}" for k, v in sorted(counter.items(), key=lambda x: -x[1])
        )

    print("\nBefore:")
    print(fmt(before))
    print("\nAfter:")
    print(fmt(after))

    if transitions:
        print(f"\n{sum(transitions.values())} conferences moved:")
        for (old, new), n in sorted(transitions.items(), key=lambda x: -x[1]):
            print(f"  {old} → {new}: {n}")

    if changes:
        # Show the first 20 actual moves so you can sanity-check them.
        sample = sorted(changes, key=lambda x: x[0])[:20]
        print("\nSample of moved conferences (first 20 alphabetically):")
        for name, old, new in sample:
            print(f"  {name[:60]:<60}  {old}  →  {new}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
