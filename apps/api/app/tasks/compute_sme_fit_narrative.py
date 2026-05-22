"""Background SME-fit-narrative task (plan 19).

Two entry points:

  * :func:`compute_sme_fit_narrative_task(conference_id, force=False)` —
    runs the narrative pipeline for one conference. Enqueued by
    :func:`run_fit_match_task` (matcher) after it commits, and by the
    admin "regenerate" route.

  * :func:`recompute_narratives_for_all` — fans out one narrative task
    per non-quarantined conference; useful after bumping the LLM model
    or the prompt version.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from app.db.models.entities import Conference
from app.db.session import get_session_factory
from app.scheduler import enqueue_now
from app.services.matcher.sme_narrative import (
    compute_narratives_for_top_smes,
)
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.narrative")


async def _do_compute(*, conference_id: str, force: bool = False) -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await compute_narratives_for_top_smes(
            session, UUID(conference_id), force=force
        )
        await session.commit()
    return result.to_stats()


async def compute_sme_fit_narrative_task(
    *, conference_id: str, force: bool = False
) -> dict[str, Any]:
    """APScheduler-callable. Tracks via :func:`run_as_job`."""
    return await run_as_job(
        "sme_fit_narrative",
        _do_compute,
        conference_id=conference_id,
        force=force,
        stats_extra={"conference_id": conference_id, "force": force},
    )


async def _do_recompute_all() -> dict[str, Any]:
    enqueued: list[str] = []
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(Conference.id).where(Conference.status != "quarantined")
            )
        ).all()
    for (cid,) in rows:
        enqueue_now(
            compute_sme_fit_narrative_task,
            job_id=f"narrative-{cid}",
            kwargs={"conference_id": str(cid), "force": False},
        )
        enqueued.append(str(cid))
    log.info("narrative.recompute_all.enqueued", count=len(enqueued))
    return {"enqueued_count": len(enqueued)}


async def recompute_narratives_for_all() -> dict[str, Any]:
    """APScheduler-callable. Fan-out helper."""
    return await run_as_job("sme_fit_narrative_recompute_all", _do_recompute_all)
