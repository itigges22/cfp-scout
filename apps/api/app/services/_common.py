"""Helpers shared across entity services: pagination, audit logging.

Kept module-private (``_common``) so it's clear this is glue, not a stable
public surface.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, func

from app.db.models.audit import AuditLog

log = structlog.get_logger("scout.services")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
async def paginate(
    db: AsyncSession,
    stmt: Select[Any],
    *,
    page: int,
    per_page: int,
) -> tuple[list[Any], int]:
    """Apply LIMIT/OFFSET to ``stmt`` and return (items, total).

    `total` is computed via ``select count() from (stmt)``. For our scale that's
    fine; if a single resource ever crosses 100k rows we'd revisit.

    ``page`` is 1-based.
    """
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1
    if per_page > 200:
        per_page = 200

    # Count using a subquery so any WHERE clauses in `stmt` apply to it too.
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    page_stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    rows = (await db.execute(page_stmt)).scalars().all()
    return list(rows), int(total)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor_label: str = "system",
) -> None:
    """Append a row to ``audit.audit_log``.

    Caller is responsible for committing the surrounding transaction; this
    function only stages the INSERT. The ``app`` role has INSERT + SELECT
    on the audit schema (defense in depth — see
    ``infra/postgres/init/02-roles-and-schemas.sql``).
    """
    db.add(
        AuditLog(
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            actor_label=actor_label,
        )
    )


def model_to_audit_dict(obj: Any) -> dict[str, Any]:
    """Serialize an ORM row into a JSON-friendly dict for audit.before/after.

    Skips relationships and SQLAlchemy internals; converts UUID + datetime
    to strings so the JSONB column accepts them.
    """
    if obj is None:
        return {}

    state = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        # JSON-friendly normalisation for the audit JSONB columns.
        if hasattr(value, "isoformat"):  # datetime / date
            state[column.name] = value.isoformat()
        elif isinstance(value, UUID):
            state[column.name] = str(value)
        else:
            state[column.name] = value
    return state
