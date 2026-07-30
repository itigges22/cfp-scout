"""Shared plumbing every CRUD service uses: paging and the audit trail.

WHAT THIS DOES
    ``paginate`` runs a statement twice — a COUNT over the same filters,
    then the LIMIT/OFFSET page — and returns ``(items, total)``.

    ``write_audit`` stages a row into ``audit.audit_log``, and
    ``model_to_audit_dict`` turns an ORM row into the JSON-friendly dict
    that row stores as before/after state. Those two are always used
    together: every one of the twelve call sites imports both.

HOW IT CONNECTS
    Called by   the entity services (talk, sme, topic, source, messaging,
                audience, series), services/discovery.py, and the
                conference routes that mutate a row — create, decisions,
                detail
    Writes      audit.audit_log
    Helpers     app/db/models.py for the AuditLog model

WORTH KNOWING
    This was named ``_common``, and the underscore promised a privacy
    that eleven importers ignored — three of them routes, which its own
    docstring told them not to be. Routes calling ``write_audit`` is
    correct rather than a leak: an audit entry records a DECISION, and
    approving or editing a conference is a decision made at the route.

    The caller commits. ``write_audit`` only stages the INSERT, so an
    audit row and the change it describes land in one transaction or
    neither does.

    The ``app`` role has INSERT + SELECT on the audit schema and nothing
    else — a DELETE against audit_log is refused at the database. Defence
    in depth; see infra/postgres/init/02-roles-and-schemas.sql.

    ``per_page`` is clamped to 200. An unbounded page is how one request
    holds a connection long enough to matter.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, func

from app.db.models import AuditLog
from app.settings import get_settings

log = structlog.get_logger("scout.services.records")





async def paginate(
    db: AsyncSession,
    stmt: Select[Any],
    *,
    page: int,
    per_page: int,
) -> tuple[list[Any], int]:
    """Apply LIMIT/OFFSET to ``stmt`` and return ``(items, total)``.

    ``page`` is 1-based. Out-of-range values are clamped rather than
    rejected — a list endpoint should not 400 because someone typed
    ``?page=0``.
    """
    page = max(page, 1)
    per_page = min(max(per_page, 1), get_settings().api_max_page_size)

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    page_stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    rows = (await db.execute(page_stmt)).scalars().all()
    return list(rows), int(total)


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
    function only stages the INSERT.
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
        state[column.name] = _json_safe(value)
    return state


def _json_safe(value: Any) -> Any:
    """Recursively coerce common non-JSON-native types.

    Handles datetime/date (isoformat), UUID (str), and lists/dicts containing
    either. Postgres ARRAY[UUID] columns surface as ``list[UUID]`` in the
    ORM, which the JSONB serializer would otherwise reject.
    """
    if hasattr(value, "isoformat"):  # datetime / date / time
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


__all__ = ["model_to_audit_dict", "paginate", "write_audit"]
