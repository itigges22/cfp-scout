"""Sources service — list / create / update / soft-delete crawl sources.

Same shape as messaging/audience/sme services. No auto-embedding here; sources
are crawl-config rows, not content.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Source
from app.schemas.common import Page
from app.schemas.source import SourceCreate, SourceRead, SourceUpdate
from app.services._common import model_to_audit_dict, paginate, write_audit

log = structlog.get_logger("scout.services.source")


async def list_sources(
    db: AsyncSession,
    *,
    page: int,
    per_page: int,
    enabled: bool | None,
    kind: str | None,
) -> Page[SourceRead]:
    stmt = select(Source)
    if enabled is not None:
        stmt = stmt.where(Source.enabled.is_(enabled))
    if kind:
        stmt = stmt.where(Source.kind == kind)
    stmt = stmt.order_by(Source.created_at.desc())
    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[SourceRead](
        items=[SourceRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_source(db: AsyncSession, source_id: UUID) -> Source:
    row = await db.get(Source, source_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No source {source_id}",
        )
    return row


async def create_source(db: AsyncSession, payload: SourceCreate) -> Source:
    row = Source(
        name=payload.name,
        url=str(payload.url),
        kind=payload.kind.value,
        crawl_cadence=payload.crawl_cadence,
        politeness_delay_seconds=payload.politeness_delay_seconds,
        enabled=payload.enabled,
        notes=payload.notes,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source conflicts with an existing row (likely duplicate URL).",
        ) from exc
    await write_audit(
        db,
        action="source.create",
        target_type="source",
        target_id=row.id,
        before=None,
        after=model_to_audit_dict(row),
        actor_label="api.create_source",
    )
    log.info("source.created", source_id=str(row.id), kind=row.kind, url=row.url)
    return row


async def update_source(db: AsyncSession, source_id: UUID, payload: SourceUpdate) -> Source:
    row = await get_source(db, source_id)
    before = model_to_audit_dict(row)

    updated_any = False
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        if field_name == "url" and value is not None:
            value = str(value)
        setattr(row, field_name, value)
        updated_any = True

    if not updated_any:
        return row

    await db.flush()
    # TimestampedMixin's updated_at has onupdate=func.now(); flush expires
    # it so the new value can be loaded. Refresh explicitly here so the
    # subsequent model_to_audit_dict() access stays synchronous.
    await db.refresh(row)
    await write_audit(
        db,
        action="source.update",
        target_type="source",
        target_id=row.id,
        before=before,
        after=model_to_audit_dict(row),
        actor_label="api.update_source",
    )
    log.info("source.updated", source_id=str(row.id))
    return row


async def disable_source(db: AsyncSession, source_id: UUID) -> Source:
    """Soft delete = ``enabled = false``. Crawls + cron skip disabled rows."""
    row = await get_source(db, source_id)
    if not row.enabled:
        return row
    before = model_to_audit_dict(row)
    row.enabled = False
    await db.flush()
    # See update_source: refresh after flush so updated_at is re-loaded
    # synchronously rather than via SQLAlchemy's expired-attribute lazy load.
    await db.refresh(row)
    await write_audit(
        db,
        action="source.disable",
        target_type="source",
        target_id=row.id,
        before=before,
        after=model_to_audit_dict(row),
        actor_label="api.disable_source",
    )
    log.info("source.disabled", source_id=str(row.id))
    return row
