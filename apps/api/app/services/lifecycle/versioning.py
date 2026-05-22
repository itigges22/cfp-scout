"""Git-blame-style content versioning (plan 25).

A SQLAlchemy ``before_flush`` event listener walks the session's "dirty"
set, and for every modified instance of a versioned entity type writes a
``audit.content_versions`` row containing the field-level diff.

Source of truth
---------------
The listener is registered globally at app startup. Feature code can't
bypass it — there is no service-layer "skip versioning" flag. CSV imports
just set ``actor_label`` via :func:`set_actor_label` before the flush.

Actor attribution
-----------------
Per-instance label via ``setattr(obj, "_actor_label", "...")`` or session-
scoped via :func:`set_actor_label` (sets a contextvar). Defaults to
``"system"`` if neither is set. Same convention for ``_reason``.

Diff shape
----------
A small field-level diff (not RFC 6902 jsonpatch) keyed by attribute
name with ``{from, to}`` pairs — directly renderable in the UI without a
client-side patch interpreter:

    {
      "fields": {
        "bio":   {"from": "Old bio…", "to": "New bio…"},
        "team":  {"from": "team",     "to": "Platform"}
      },
      "version_number": 7
    }

Versioned entity types
----------------------
``conferences``, ``messaging_documents``, ``audience_profiles``, ``smes``,
``topics``, ``conference_series``, ``decisions``. The matcher's
``matches`` rows aren't versioned (they're matcher OUTPUT, not human
edits; the algorithm_version + computed_at carry the provenance).
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

_log = logging.getLogger("scout.lifecycle.versioning")

# Maps SQLAlchemy table name -> friendly entity_type label stored in
# audit.content_versions.entity_type. Keep this in sync as new versioned
# tables land.
VERSIONED_ENTITY_TYPES: Final[dict[str, str]] = {
    "conferences": "conference",
    "messaging_documents": "messaging_document",
    "audience_profiles": "audience_profile",
    "smes": "sme",
    "topics": "topic",
    "conference_series": "conference_series",
    "decisions": "decision",
}

# Attribute names we never include in the diff (no signal, lots of noise).
_IGNORED_ATTRS: Final[set[str]] = {
    "updated_at",  # bumped by onupdate=now() on every UPDATE; tautological in diff
    "created_at",  # never changes after insert
}


# ---------------------------------------------------------------------------
# Per-session actor + reason attribution
# ---------------------------------------------------------------------------
_actor_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "scout_actor_label", default=None
)
_reason_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "scout_change_reason", default=None
)


def set_actor_label(label: str) -> None:
    """Set the actor label for any versioning writes on this asyncio task /
    thread. Most service code can ignore this — the SQLAlchemy listener
    falls back to ``"system"``. CSV imports / admin tools call this to get
    "csv_import:filename.csv" or "api.user_decision" in the audit trail."""
    _actor_var.set(label)


def clear_actor_label() -> None:
    _actor_var.set(None)


def set_reason(reason: str) -> None:
    _reason_var.set(reason)


def clear_reason() -> None:
    _reason_var.set(None)


# ---------------------------------------------------------------------------
# Listener registration
# ---------------------------------------------------------------------------
def register_versioning_listeners() -> None:
    """Wire the global before_flush listener. Call once at app startup.

    Idempotent — sqlalchemy.event.listen with the same handler is a no-op
    on the second call, but we still guard via the module-level flag for
    clarity (tests + restarts).
    """
    global _registered
    if _registered:
        return
    event.listen(Session, "before_flush", _on_before_flush)
    _registered = True
    _log.info("scout.versioning.listener_registered")


_registered = False


# ---------------------------------------------------------------------------
# The listener
# ---------------------------------------------------------------------------
def _on_before_flush(session: Session, flush_context, instances) -> None:
    """For each modified versioned instance, append a content_versions row.

    Runs synchronously inside the flush — adding session.add() rows inside
    a flush is supported by SQLAlchemy as long as we do it before any
    pre-INSERT/UPDATE state machine progresses. SQLAlchemy will pick up
    the new ContentVersion rows on this same flush.
    """
    # Lazy-import so this module stays importable in contexts where the
    # ORM hasn't been finalized yet (e.g. Alembic env.py).
    from app.db.models.audit import ContentVersion

    actor = _actor_var.get() or "system"
    reason = _reason_var.get()

    new_rows: list[ContentVersion] = []
    for obj in list(session.dirty):
        entity_type = VERSIONED_ENTITY_TYPES.get(getattr(obj.__table__, "name", ""))
        if entity_type is None:
            continue
        if not session.is_modified(obj, include_collections=False):
            continue

        changes = _changed_fields(obj)
        if not changes:
            # `dirty` can include rows whose only mutation was an
            # autoflush-internal attribute set; if no real fields changed,
            # don't write a version row.
            continue

        entity_id = getattr(obj, "id", None)
        if not isinstance(entity_id, uuid.UUID):
            # Versioned rows always have a uuid PK; if not, something's off.
            continue

        next_v = _next_version_number(session, entity_type, entity_id)
        cv = ContentVersion(
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=next_v,
            diff={"fields": changes, "version_number": next_v},
            actor_label=actor,
            reason=reason,
        )
        new_rows.append(cv)

    for cv in new_rows:
        session.add(cv)


def _changed_fields(obj: Any) -> dict[str, dict[str, Any]]:
    """Walk the instance's attribute history; return {attr: {from, to}}
    for attributes whose value actually changed."""
    from sqlalchemy import inspect as sql_inspect

    state = sql_inspect(obj)
    changes: dict[str, dict[str, Any]] = {}
    for attr in state.attrs:
        if attr.key in _IGNORED_ATTRS:
            continue
        history = attr.history
        if not history.has_changes():
            continue
        # has_changes() can be true for collection appends without
        # element identity change. We only care about scalar / array
        # column edits in v1; deleted/added/unchanged are typed lists.
        deleted = list(history.deleted or ())
        added = list(history.added or ())
        # If both are empty (collection-only ops we don't model yet), skip.
        if not deleted and not added:
            continue
        old = deleted[0] if deleted else None
        new = added[0] if added else None
        if old == new:
            continue
        changes[attr.key] = {
            "from": _json_safe(old),
            "to": _json_safe(new),
        }
    return changes


def _next_version_number(session: Session, entity_type: str, entity_id: uuid.UUID) -> int:
    """SELECT max(version_number)+1 — small N per entity, cheap query."""
    from app.db.models.audit import ContentVersion

    current = session.execute(
        select(func.coalesce(func.max(ContentVersion.version_number), 0))
        .where(ContentVersion.entity_type == entity_type)
        .where(ContentVersion.entity_id == entity_id)
    ).scalar_one()
    return int(current) + 1


# ---------------------------------------------------------------------------
# JSON normalisation (mirrors _common._json_safe but local + minimal-dep)
# ---------------------------------------------------------------------------
def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)
