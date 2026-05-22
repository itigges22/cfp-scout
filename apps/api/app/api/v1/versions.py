"""/api/v1/versions — content history (plan 25).

Single endpoint surface in pass 1:
  * ``GET /versions/entity/{entity_type}/{entity_id}`` — full history (oldest first)

Versioned entity_type values match :data:`VERSIONED_ENTITY_TYPES`
(``conference``, ``messaging_document``, ``audience_profile``, ``sme``,
``topic``, ``conference_series``, ``decision``).

Pass 2 will add the "restore this version" mutation — a non-destructive
write that creates a NEW version re-applying the older state.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.db.models.audit import ContentVersion
from app.db.session import DbSession
from app.services.lifecycle import VERSIONED_ENTITY_TYPES

log = structlog.get_logger("scout.api.versions")
router = APIRouter(prefix="/api/v1/versions", tags=["versions"])


class ContentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: UUID
    entity_type: str
    entity_id: UUID
    version_number: int
    diff: dict
    actor_label: str
    changed_at: datetime
    reason: str | None


@router.get("/entity/{entity_type}/{entity_id}")
async def history_for_entity(
    db: DbSession,
    entity_type: str,
    entity_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Full version history (oldest first) for one entity."""
    if entity_type not in VERSIONED_ENTITY_TYPES.values():
        raise HTTPException(
            status_code=400,
            detail=(f"entity_type must be one of {sorted(VERSIONED_ENTITY_TYPES.values())}"),
        )
    rows = (
        (
            await db.execute(
                select(ContentVersion)
                .where(ContentVersion.entity_type == entity_type)
                .where(ContentVersion.entity_id == entity_id)
                .order_by(ContentVersion.version_number.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "versions": [ContentVersionRead.model_validate(r).model_dump(mode="json") for r in rows],
    }
