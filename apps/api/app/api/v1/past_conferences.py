"""/api/v1/past-conferences routes — CRUD + CSV import."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile, status

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


@router.delete("/{pc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_(
    db: DbSession,
    pc_id: UUID,
    actor_label: str = Query("system"),
) -> Response:
    """Hard-delete a past-conference row."""
    await past_conference_service.delete_past_conference(
        db, pc_id, actor_label=actor_label
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.post("/import-calendar-sync")
async def import_calendar_sync(
    db: DbSession,
    file: Annotated[
        UploadFile,
        File(
            description=(
                "CSV exported from the AI BU Developer Marketing 2026 Events "
                "spreadsheet (Events tab). Same shape teammate/"
                "google-calendar-events-sync expects. Falls back to "
                "Docling + LLM extraction if the linter rejects the file."
            )
        ),
    ],
    apply: bool = Query(
        default=False,
        description=(
            "Preview vs apply. False = compute decisions + return the "
            "per-row breakdown without writing. True = persist everything."
        ),
    ),
    fallback_year: int = Query(
        default=2026,
        ge=2020,
        le=2030,
        description="Year to assume when a date cell has no year (e.g. 'June 14th').",
    ),
    actor_label: str = Query(default="calendar_sync_import", max_length=120),
) -> dict[str, object]:
    """Import the team's calendar-sync events CSV.

    Strict linter first (same column shape as the upstream calendar-sync
    cron). On format error, falls back to Docling + LLM extraction so a
    PDF / XLSX / weird CSV can still land. Routes per row:

      - Complete=TRUE → app.past_conferences (attendees resolved against
        Sme.full_name; unmatched names surfaced as warnings).
      - Complete=FALSE → app.conferences (status='approved' since the
        team has committed to attending).

    Preview-then-apply: call with apply=false first to see the
    decisions, then re-post with apply=true to persist.
    """
    from app.services.calendar_sync import import_calendar_sync_csv

    content = await file.read()
    outcome = await import_calendar_sync_csv(
        db,
        content=content,
        filename=file.filename or "upload.csv",
        apply=apply,
        fallback_year=fallback_year,
        actor_label=actor_label,
    )
    if apply:
        await db.commit()
    return outcome.to_dict()
