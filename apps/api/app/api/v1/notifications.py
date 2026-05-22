"""/api/v1/notifications — bell-badge surface (plan 24).

Endpoints:
  * ``GET  /notifications``                — paginated list
  * ``GET  /notifications/latest``         — latest unread (or any) by kind
  * ``GET  /notifications/unread-count``   — bell badge count
  * ``POST /notifications/{id}/dismiss``   — mark seen
  * ``GET  /notifications/cfp-digest/markdown`` — copy-to-clipboard helper

Notifications are global (single-user install per ADR-0001) — there is no
per-user scoping.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.db.models.ops import Notification
from app.db.session import DbSession
from app.services.digest.cfp import (
    BUCKET_BOUNDS,
    DigestResult,
    to_markdown,
)

log = structlog.get_logger("scout.api.notifications")
router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    kind: str
    payload: dict
    seen: bool
    created_at: datetime


class NotificationsList(BaseModel):
    items: list[NotificationRead]
    total: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=NotificationsList)
async def list_notifications(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    kind: str | None = Query(default=None),
    include_seen: bool = Query(default=True),
) -> NotificationsList:
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    if not include_seen:
        stmt = stmt.where(Notification.seen.is_(False))
    rows = (await db.execute(stmt)).scalars().all()

    count_stmt = select(func.count(Notification.id))
    if kind:
        count_stmt = count_stmt.where(Notification.kind == kind)
    if not include_seen:
        count_stmt = count_stmt.where(Notification.seen.is_(False))
    total = (await db.execute(count_stmt)).scalar_one()

    return NotificationsList(
        items=[NotificationRead.model_validate(r) for r in rows],
        total=int(total),
    )


@router.get("/unread-count")
async def unread_count(db: DbSession, kind: str | None = Query(default=None)) -> dict:
    """Bell-badge count. Filterable by kind so the UI can spin separate badges."""
    stmt = select(func.count(Notification.id)).where(Notification.seen.is_(False))
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    n = (await db.execute(stmt)).scalar_one()
    return {"count": int(n), "kind": kind}


@router.get("/latest", response_model=NotificationRead)
async def latest(
    db: DbSession,
    kind: str = Query(...),
    unread_only: bool = Query(default=False),
) -> NotificationRead:
    """Latest notification of the given kind. 404 if none exist."""
    stmt = (
        select(Notification)
        .where(Notification.kind == kind)
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    if unread_only:
        stmt = stmt.where(Notification.seen.is_(False))
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No notification of kind {kind!r}",
        )
    return NotificationRead.model_validate(row)


@router.post("/{notification_id}/dismiss", status_code=status.HTTP_200_OK)
async def dismiss(db: DbSession, notification_id: UUID) -> dict:
    row = await db.get(Notification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No notification {notification_id}")
    if not row.seen:
        row.seen = True
        await db.flush()
        await db.commit()
    return {"id": str(row.id), "seen": True}


@router.get("/cfp-digest/markdown")
async def cfp_digest_markdown(db: DbSession) -> dict:
    """Re-render the latest cfp_digest notification as Markdown for the
    UI's copy-to-clipboard button. Returns ``{"markdown": "...",
    "generated_at": "...", "n_entries": N}``. 404 if no digest exists yet.
    """
    row = (
        await db.execute(
            select(Notification)
            .where(Notification.kind == "cfp_digest")
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No cfp_digest yet.")

    # Re-hydrate just enough of DigestResult to feed to_markdown(). We
    # rebuild from the persisted payload rather than re-running the
    # builder — that way the formatter is a pure function over whatever
    # snapshot was persisted.
    payload = row.payload or {}
    buckets: dict[str, list] = {}
    for _, _, key in BUCKET_BOUNDS:
        raw = payload.get("buckets", {}).get(key, [])
        buckets[key] = [_dict_to_entry(d) for d in raw]
    result = DigestResult(
        generated_at=payload.get("generated_at", row.created_at.isoformat()),
        notification_id=str(row.id),
        buckets=buckets,
        stats={k: len(v) for k, v in buckets.items()},
    )
    return {
        "markdown": to_markdown(result),
        "generated_at": result.generated_at,
        "n_entries": sum(result.stats.values()),
    }


def _dict_to_entry(d: dict):
    """Lightweight dict->DigestEntry hydration (avoid importing the
    dataclass everywhere)."""
    from app.services.digest.cfp import DigestEntry

    return DigestEntry(
        conference_id=d.get("conference_id", ""),
        name=d.get("name", ""),
        slug=d.get("slug", ""),
        status=d.get("status", ""),
        overall_score=d.get("overall_score"),
        deadline_kind=d.get("deadline_kind", "other"),
        deadline_date=d.get("deadline_date", ""),
        days_until=int(d.get("days_until", 0)),
        top_sme_id=d.get("top_sme_id"),
        top_sme_name=d.get("top_sme_name"),
        website=d.get("website"),
        location=d.get("location"),
    )
