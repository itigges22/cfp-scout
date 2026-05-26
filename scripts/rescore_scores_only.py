"""Bulk rescore — scores only, no rationale / no narrative LLM calls.

Why this exists: the production ``run_fit_match`` pipeline does the
three matcher stages PLUS one LLM rationale call PLUS enqueues a
narrative job per conference. For a 583-conference rescore that's
thousands of LLM calls, which trips the MaaS per-user 120 req/min
limit and stretches the run to many hours.

For verifying the enrichment-vs-baseline delta we only need the three
component scores. Rationale + narratives can be regenerated lazily as
the user opens conference detail pages.

Run inside the api container::

    podman cp scripts/rescore_scores_only.py scout-api:/tmp/rescore_scores_only.py
    podman exec scout-api /app/.venv/bin/python /tmp/rescore_scores_only.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.db.models.entities import Conference
from app.db.models.matching import Match
from app.db.session import get_session_factory
from app.services import settings_overrides
from app.services.matcher._scoring import clamp01
from app.services.matcher.messaging import stage_a_messaging_fit
from app.services.matcher.pillars import stage_b_pillar_alignment
from app.services.matcher.pipeline import ALGORITHM_VERSION
from app.services.matcher.smes import stage_c_sme_match
from app.settings import get_settings

CONCURRENCY = 8


async def _bootstrap_settings() -> None:
    factory = get_session_factory()
    async with factory() as s:
        await settings_overrides.load_from_db(s)
    get_settings.cache_clear()


async def _score_one(conf_id: UUID, sem: asyncio.Semaphore, counters: dict, total: int) -> None:
    async with sem:
        factory = get_session_factory()
        async with factory() as db:
            settings = get_settings()
            try:
                ms = await stage_a_messaging_fit(db, conf_id)
                pl = await stage_b_pillar_alignment(db, conf_id)
                sm = await stage_c_sme_match(db, conf_id, gate=settings.match_s_gate)
                overall = clamp01(
                    settings.match_w_messaging * ms.score
                    + settings.match_w_pillar * pl.score
                    + settings.match_w_sme * sm.score
                )
                rec_uuids = [UUID(r.sme_id) for r in sm.recommendations]
                # Upsert by (conference_id, algorithm_version). Don't
                # touch rationale_text — preserve whatever was there.
                existing = (
                    await db.execute(
                        select(Match)
                        .where(Match.conference_id == conf_id)
                        .where(Match.algorithm_version == ALGORITHM_VERSION)
                    )
                ).scalar_one_or_none()
                now = datetime.now(tz=UTC)
                if existing is None:
                    db.add(
                        Match(
                            conference_id=conf_id,
                            messaging_score=ms.score,
                            pillar_score=pl.score,
                            sme_score=sm.score,
                            overall_score=overall,
                            recommended_sme_ids=rec_uuids,
                            rationale_text="",
                            algorithm_version=ALGORITHM_VERSION,
                            computed_at=now,
                        )
                    )
                else:
                    existing.messaging_score = ms.score
                    existing.pillar_score = pl.score
                    existing.sme_score = sm.score
                    existing.overall_score = overall
                    existing.recommended_sme_ids = rec_uuids
                    existing.computed_at = now
                await db.commit()
                counters["ok"] += 1
            except Exception as exc:  # noqa: BLE001
                counters["failed"] += 1
                print(f"  FAILED for {conf_id}: {exc}")

    counters["done"] += 1
    if counters["done"] % 50 == 0:
        elapsed = time.monotonic() - counters["_t0"]
        rate = counters["done"] / max(elapsed, 0.001)
        eta = (total - counters["done"]) / max(rate, 0.001)
        print(
            f"  {counters['done']}/{total} ok={counters['ok']} failed={counters['failed']} "
            f"({rate:.1f}/s · ETA {eta:.0f}s)"
        )


async def main() -> int:
    await _bootstrap_settings()
    s = get_settings()
    print(
        f"Weights: msg={s.match_w_messaging} pil={s.match_w_pillar} sme={s.match_w_sme} · "
        f"algorithm_version={ALGORITHM_VERSION}"
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
    print(f"Rescoring {total} conferences with concurrency {CONCURRENCY}.")

    sem = asyncio.Semaphore(CONCURRENCY)
    counters: dict = {"ok": 0, "failed": 0, "done": 0, "_t0": time.monotonic()}
    await asyncio.gather(*(_score_one(r.id, sem, counters, total) for r in rows))

    elapsed = time.monotonic() - counters["_t0"]
    print(
        f"\nDone in {elapsed:.1f}s. ok={counters['ok']} failed={counters['failed']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
