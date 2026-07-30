"""Routes for the audience vocabulary.

HOW IT CONNECTS
    Calls       services/taxonomy.py, services/records.py
    Serves      /api/v1/audience-profiles*

WORTH KNOWING
    Note the path asymmetry: topics are served from /topics but audiences
    from /audience-profiles. Not a typo — the SPA calls both, and the
    contract test would fail if either moved.

    Both defined the same four CRUD handler names; they now say which
    noun they operate on.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Query, status

from app.db.session import DbSession
from app.schemas import (
    AudienceProfileCreate,
    AudienceProfileRead,
    AudienceProfileUpdate,
    Page,
)
from app.services import taxonomy

log = structlog.get_logger("scout.api.taxonomy")


# ==========================================================================
# audiences.py
# ==========================================================================


_r_audiences = APIRouter(prefix="/api/v1/audience-profiles", tags=["audiences"])


@_r_audiences.get("", response_model=Page[AudienceProfileRead])
async def list_audiences(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: str | None = None,
    is_active: bool | None = None,
    pillar_id: UUID | None = None,
) -> Page[AudienceProfileRead]:
    return await taxonomy.list_audience_profiles(
        db, page=page, per_page=per_page, q=q, is_active=is_active, pillar_id=pillar_id
    )


@_r_audiences.get("/{aud_id}", response_model=AudienceProfileRead)
async def get_audience(db: DbSession, aud_id: UUID) -> AudienceProfileRead:
    obj = await taxonomy.get_audience_profile(db, aud_id)
    return AudienceProfileRead.model_validate(obj)


@_r_audiences.post(
    "",
    response_model=AudienceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_audience(
    db: DbSession,
    payload: AudienceProfileCreate,
    actor_label: str = Query("system"),
) -> AudienceProfileRead:
    obj = await taxonomy.create_audience_profile(db, payload, actor_label=actor_label)
    return AudienceProfileRead.model_validate(obj)


@_r_audiences.put("/{aud_id}", response_model=AudienceProfileRead)
async def update_audience(
    db: DbSession,
    aud_id: UUID,
    payload: AudienceProfileUpdate,
    actor_label: str = Query("system"),
) -> AudienceProfileRead:
    obj = await taxonomy.update_audience_profile(
        db, aud_id, payload, actor_label=actor_label
    )
    return AudienceProfileRead.model_validate(obj)


@_r_audiences.delete("/{aud_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_(
    db: DbSession,
    aud_id: UUID,
    actor_label: str = Query("system"),
) -> None:
    await taxonomy.deactivate_audience_profile(db, aud_id, actor_label=actor_label)


router = APIRouter()
router.include_router(_r_audiences)
