"""Background team-recommendation task (plan 32).

Pure-algorithmic; no LLM cost. Enqueued by the matcher pipeline after
``run_fit_match`` commits, and by ``POST /admin/matcher/teams-now/{id}``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.db.session import get_session_factory
from app.services.matcher.teams import recommend_teams
from app.tasks._runner import run_as_job

log = structlog.get_logger("scout.tasks.teams")


async def _do_teams(*, conference_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        result = await recommend_teams(session, UUID(conference_id))
        await session.commit()
    return {
        "conference_id": result.conference_id,
        "candidate_count": result.candidate_count,
        "sizes": sorted(result.by_size.keys()),
    }


async def recommend_teams_task(*, conference_id: str) -> dict[str, Any]:
    """APScheduler-callable; wraps in run_as_job for ingest_jobs trail."""
    return await run_as_job(
        "recommend_teams",
        _do_teams,
        conference_id=conference_id,
        stats_extra={"conference_id": conference_id},
    )
