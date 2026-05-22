"""CRUD + assignment helpers for conference_series (plan 23).

Series assignment is a real edit: the SME matcher's past-attendance bonus
depends on it (plan 18). After every assign/unassign we enqueue a
``run_fit_match_task`` for the affected conference so the dashboard
reflects the new score promptly.

Caller commits.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, ConferenceSeries
from app.services._common import model_to_audit_dict, write_audit
from app.services.graph import invalidate as invalidate_graph

log = structlog.get_logger("scout.series.crud")


# ---------------------------------------------------------------------------
# Series CRUD
# ---------------------------------------------------------------------------
async def create_series(
    db: AsyncSession,
    *,
    canonical_name: str,
    aliases: list[str] | None = None,
    description: str = "",
    typical_month: int | None = None,
    typical_topics: list[str] | None = None,
    homepage: str | None = None,
    actor_label: str = "system",
) -> ConferenceSeries:
    row = ConferenceSeries(
        canonical_name=canonical_name.strip(),
        aliases=list(aliases or []),
        description=description.strip(),
        typical_month=typical_month,
        typical_topics=list(typical_topics or []),
        homepage=homepage,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A series named {canonical_name!r} already exists.",
        ) from exc
    await db.refresh(row)
    await write_audit(
        db,
        action="series.create",
        target_type="conference_series",
        target_id=row.id,
        before=None,
        after=model_to_audit_dict(row),
        actor_label=actor_label,
    )
    invalidate_graph()
    log.info("series.created", series_id=str(row.id), name=row.canonical_name)
    return row


async def update_series(
    db: AsyncSession,
    series_id: UUID,
    *,
    canonical_name: str | None = None,
    aliases: list[str] | None = None,
    description: str | None = None,
    typical_month: int | None = None,
    typical_topics: list[str] | None = None,
    homepage: str | None = None,
    is_active: bool | None = None,
    actor_label: str = "system",
) -> ConferenceSeries:
    row = await db.get(ConferenceSeries, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No conference_series {series_id}")
    before = model_to_audit_dict(row)

    if canonical_name is not None:
        row.canonical_name = canonical_name.strip()
    if aliases is not None:
        row.aliases = list(aliases)
    if description is not None:
        row.description = description.strip()
    if typical_month is not None:
        row.typical_month = typical_month
    if typical_topics is not None:
        row.typical_topics = list(typical_topics)
    if homepage is not None:
        row.homepage = homepage
    if is_active is not None:
        row.is_active = is_active

    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Series rename collides with an existing canonical_name.",
        ) from exc
    await db.refresh(row)
    await write_audit(
        db,
        action="series.update",
        target_type="conference_series",
        target_id=row.id,
        before=before,
        after=model_to_audit_dict(row),
        actor_label=actor_label,
    )
    invalidate_graph()
    return row


async def deactivate_series(
    db: AsyncSession, series_id: UUID, *, actor_label: str = "system"
) -> ConferenceSeries:
    row = await db.get(ConferenceSeries, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No conference_series {series_id}")
    if not row.is_active:
        return row
    before = model_to_audit_dict(row)
    row.is_active = False
    await db.flush()
    await db.refresh(row)
    await write_audit(
        db,
        action="series.deactivate",
        target_type="conference_series",
        target_id=row.id,
        before=before,
        after=model_to_audit_dict(row),
        actor_label=actor_label,
    )
    invalidate_graph()
    return row


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------
async def assign_conference_to_series(
    db: AsyncSession,
    series_id: UUID,
    conference_id: UUID,
    *,
    actor_label: str = "system",
) -> Conference:
    """Set ``conferences.series_id``; recompute the matcher for that
    conference asynchronously so the past-attendance bonus reflects the
    new link in the dashboard."""
    series = await db.get(ConferenceSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"No conference_series {series_id}")
    if not series.is_active:
        raise HTTPException(
            status_code=409,
            detail=f"Series {series_id} is deactivated; reactivate before assigning.",
        )

    conf = await db.get(Conference, conference_id)
    if conf is None:
        raise HTTPException(status_code=404, detail=f"No conference {conference_id}")

    before = model_to_audit_dict(conf)
    conf.series_id = series.id
    await db.flush()
    await db.refresh(conf)
    await write_audit(
        db,
        action="series.assign",
        target_type="conference",
        target_id=conf.id,
        before=before,
        after=model_to_audit_dict(conf),
        actor_label=actor_label,
    )
    invalidate_graph()
    _enqueue_matcher_recompute(conf.id)
    return conf


async def unassign_conference_from_series(
    db: AsyncSession,
    conference_id: UUID,
    *,
    actor_label: str = "system",
) -> Conference:
    conf = await db.get(Conference, conference_id)
    if conf is None:
        raise HTTPException(status_code=404, detail=f"No conference {conference_id}")
    if conf.series_id is None:
        return conf
    before = model_to_audit_dict(conf)
    conf.series_id = None
    await db.flush()
    await db.refresh(conf)
    await write_audit(
        db,
        action="series.unassign",
        target_type="conference",
        target_id=conf.id,
        before=before,
        after=model_to_audit_dict(conf),
        actor_label=actor_label,
    )
    invalidate_graph()
    _enqueue_matcher_recompute(conf.id)
    return conf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _enqueue_matcher_recompute(conference_id: UUID) -> None:
    """Local-import the scheduler + task to avoid a top-level import cycle
    (scheduler -> tasks -> series_service -> scheduler)."""
    from app.scheduler import enqueue_now
    from app.tasks.run_fit_match import run_fit_match_task

    enqueue_now(
        run_fit_match_task,
        job_id=f"match-{conference_id}",
        kwargs={"conference_id": str(conference_id)},
    )
