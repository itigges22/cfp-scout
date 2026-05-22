"""/api/v1/past-conferences routes — CRUD + CSV import."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile, status

from app.db.session import DbSession
from app.schemas.common import Page
from app.schemas.past_conference import (
    PastConferenceCreate,
    PastConferenceRead,
    PastConferenceUpdate,
)
from app.services import past_conference_service

router = APIRouter(prefix="/api/v1/past-conferences", tags=["past_conferences"])


@router.get("", response_model=Page[PastConferenceRead])
async def list_(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    q: str | None = None,
    year: int | None = None,
) -> Page[PastConferenceRead]:
    return await past_conference_service.list_past_conferences(
        db, page=page, per_page=per_page, q=q, year=year
    )


@router.get("/{pc_id}", response_model=PastConferenceRead)
async def get_(db: DbSession, pc_id: UUID) -> PastConferenceRead:
    obj = await past_conference_service.get_past_conference(db, pc_id)
    return PastConferenceRead.model_validate(obj)


@router.post("", response_model=PastConferenceRead, status_code=status.HTTP_201_CREATED)
async def create_(
    db: DbSession,
    payload: PastConferenceCreate,
    actor_label: str = Query("system"),
) -> PastConferenceRead:
    obj = await past_conference_service.create_past_conference(db, payload, actor_label=actor_label)
    return PastConferenceRead.model_validate(obj)


@router.put("/{pc_id}", response_model=PastConferenceRead)
async def update_(
    db: DbSession,
    pc_id: UUID,
    payload: PastConferenceUpdate,
    actor_label: str = Query("system"),
) -> PastConferenceRead:
    obj = await past_conference_service.update_past_conference(
        db, pc_id, payload, actor_label=actor_label
    )
    return PastConferenceRead.model_validate(obj)


@router.post("/import")
async def import_csv(
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV per docs/ops/data-guardrails.md")],
    ignore_errors: bool = Query(
        False,
        description="When true, commit valid rows and report errors instead of all-or-nothing.",
    ),
    actor_label: str = Query("csv_import"),
) -> dict[str, object]:
    """Bulk import past-conference rows from a CSV.

    Canonical columns: name, year, attended_by_names, role, session_type, notes.
    `attended_by_names` is semicolon-separated; resolved by case-insensitive
    match against `smes.full_name`. Unknown names error out per row.

    Returns ``{imported, skipped, errors}``. With ``ignore_errors=false`` (the
    default) any error rolls back the whole import.
    """
    content = await file.read()
    return await past_conference_service.import_past_conferences_csv(
        db,
        content,
        ignore_errors=ignore_errors,
        actor_label=actor_label,
    )
