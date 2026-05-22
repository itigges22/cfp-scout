"""/api/v1/conferences/{id}/brief — denormalized brief payload (plan 33).

Single endpoint:

  * ``GET /conferences/{id}/brief?team_size=1|2|3``

Returns one JSON object containing every section the brief page needs
(header, scores, rationale, attendees, CFP info, past engagement,
talking points, footer). The frontend renders it as a print-optimized
one-pager and the user prints to PDF from their browser.

Cached for 5 minutes per ``(conference_id, team_size)`` in the api
process. ``?force=true`` bypasses the cache for verification + admin
debugging.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.db.session import DbSession
from app.services.brief import BriefNotFoundError, build_brief

log = structlog.get_logger("scout.api.briefs")
router = APIRouter(prefix="/api/v1/conferences", tags=["briefs"])


@router.get("/{conference_id}/brief")
async def get_brief(
    db: DbSession,
    conference_id: UUID,
    team_size: int = Query(default=1, ge=1, le=3),
    force: bool = Query(default=False),
) -> dict:
    try:
        return await build_brief(db, conference_id, team_size=team_size, force=force)
    except BriefNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
