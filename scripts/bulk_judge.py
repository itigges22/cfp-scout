"""One-shot: run Stage D (LLM-as-judge) for every conference + refresh overall.

Walks every non-quarantined conference, calls
:func:`judge_conference` to produce a calibrated 0..1 cross-encoder
score + rationale, then recomputes ``overall_score`` from the
weighted blend of the four stages and writes both judge fields +
the refreshed overall back to ``app.matches``.

Concurrency is bounded by the LLM client's process-wide semaphore;
this script kicks off bounded-gather rather than serial so the run
finishes in minutes instead of hours, but no faster than the
MaaS per-user rate limit allows.

Run inside the api container::

    podman cp scripts/bulk_judge.py scout-api:/tmp/bulk_judge.py
    podman exec scout-api /app/.venv/bin/python /tmp/bulk_judge.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.models.entities import Conference, StrategicPillar
from app.db.models.matching import Match
from app.db.session import get_session_factory
from app.services import settings_overrides
from app.services.matcher._scoring import clamp01
from app.services.matcher.judge import judge_conference
from app.services.matcher.pipeline import ALGORITHM_VERSION
from app.settings import get_settings

CONCURRENCY = 4  # under the MaaS user-level RPM limit


async def _bootstrap_settings() -> None:
    factory = get_session_factory()
    async with factory() as s:
        await settings_overrides.load_from_db(s)
    get_settings.cache_clear()


async def _process_one(
    conf_id, sem: asyncio.Semaphore, counters: dict, total: int
) -> None:
    async with sem:
        factory = get_session_factory()
        async with factory() as db:
            settings = get_settings()
            conf = (
                await db.execute(select(Conference).where(Conference.id == conf_id))
            ).scalar_one_or_none()
            if conf is None:
                counters["missing"] += 1
                return
            pillars = (
                await db.execute(
                    select(StrategicPillar).order_by(StrategicPillar.display_order)
                )
            ).scalars().all()
            judge = await judge_conference(db=db, conference=conf, pillars=pillars)
            if judge is None:
                counters["llm_failed"] += 1
                # Don't touch overall_score on failure — leave it as-is.
                await db.commit()
                return

            # Pull the existing match row so we can recompute overall.
            match = (
                await db.execute(
                    select(Match)
                    .where(Match.conference_id == conf.id)
                    .where(Match.algorithm_version == ALGORITHM_VERSION)
                )
            ).scalar_one_or_none()
            if match is None:
                counters["no_match"] += 1
                await db.commit()
                return

            w_msg = settings.match_w_messaging
            w_pil = settings.match_w_pillar
            w_sme = settings.match_w_sme
            w_judge = settings.match_w_judge
            total_w = w_msg + w_pil + w_sme + w_judge or 1.0
            overall = clamp01(
                (
                    w_msg * match.messaging_score
                    + w_pil * match.pillar_score
                    + w_sme * match.sme_score
                    + w_judge * judge.score
                )
                / total_w
            )
            await db.execute(
                update(Match)
                .where(Match.id == match.id)
                .values(
                    judge_score=judge.score,
                    judge_rationale=judge.rationale,
                    overall_score=overall,
                    computed_at=datetime.now(tz=UTC),
                )
            )
            await db.commit()
            counters["ok"] += 1

    counters["done"] += 1
    if counters["done"] % 25 == 0:
        elapsed = time.monotonic() - counters["_t0"]
        rate = counters["done"] / max(elapsed, 0.001)
        eta = (total - counters["done"]) / max(rate, 0.001)
        print(
            f"  {counters['done']}/{total} ok={counters['ok']} "
            f"llm_fail={counters['llm_failed']} no_match={counters['no_match']} "
            f"({rate:.1f}/s · ETA {eta / 60:.1f}min)"
        )


async def main() -> int:
    await _bootstrap_settings()
    s = get_settings()
    print(
        f"LLM dry_run={s.llm_dry_run} chat={s.llm_chat_model} "
        f"weights msg={s.match_w_messaging} pil={s.match_w_pillar} "
        f"sme={s.match_w_sme} judge={s.match_w_judge}"
    )

    factory = get_session_factory()
    async with factory() as db:
        rows = (
            await db.execute(
                select(Conference.id)
                .where(Conference.status != "quarantined")
                .order_by(Conference.created_at)
            )
        ).all()
    total = len(rows)
    print(f"Judging {total} conferences with concurrency {CONCURRENCY}.")

    sem = asyncio.Semaphore(CONCURRENCY)
    counters: dict = {
        "ok": 0,
        "llm_failed": 0,
        "no_match": 0,
        "missing": 0,
        "done": 0,
        "_t0": time.monotonic(),
    }
    await asyncio.gather(*(_process_one(r.id, sem, counters, total) for r in rows))

    elapsed = time.monotonic() - counters["_t0"]
    print(
        f"\nDone in {elapsed / 60:.1f}min. ok={counters['ok']} "
        f"llm_failed={counters['llm_failed']} no_match={counters['no_match']} "
        f"missing={counters['missing']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
