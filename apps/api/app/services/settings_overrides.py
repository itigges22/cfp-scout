"""Runtime overrides for ``app/settings.py`` (P3 UX work).

Persistence is in ``app.app_setting_overrides`` (one row per name).
The override dict is loaded into memory at api startup; subsequent
``PATCH /api/v1/admin/settings`` calls write through to both the DB and
the dict, then clear ``get_settings.cache_clear()`` so the next reader
sees the new value.

Type coercion is deliberately strict — we encode values as JSON in the
table so booleans, integers, floats, and lists round-trip without
``"True"`` / ``"true"`` ambiguity.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ops import AppSettingOverride

log = structlog.get_logger("scout.settings_overrides")

# Module-level state. ``Settings()`` reads this via the
# ``apply_overrides`` indirection in ``app/settings.py``.
_OVERRIDES: dict[str, Any] = {}


def current() -> dict[str, Any]:
    """Snapshot of the in-memory override dict. Read-only — callers must
    not mutate the returned object."""
    return dict(_OVERRIDES)


def get(name: str) -> Any:
    """Lookup a single override. Returns ``None`` if not set."""
    return _OVERRIDES.get(name)


def has(name: str) -> bool:
    return name in _OVERRIDES


# ---------------------------------------------------------------------------
# Async DB integration
# ---------------------------------------------------------------------------
async def load_from_db(db: AsyncSession, *, quiet: bool = False) -> dict[str, Any]:
    """Populate the in-memory dict from the table.

    Called once at startup and then periodically by the refresh loop
    (``app.services.settings_refresh``) so overrides written by another
    process — a sibling api replica or the standalone scheduler — land
    here without a restart. ``quiet=True`` suppresses the loaded log
    line (the refresh loop logs only on actual change).
    """
    rows = (await db.execute(select(AppSettingOverride))).scalars().all()
    new_dict: dict[str, Any] = {}
    for row in rows:
        try:
            new_dict[row.name] = json.loads(row.value)
        except json.JSONDecodeError:
            log.warning(
                "settings_overrides.bad_json",
                name=row.name,
                value=row.value[:80],
            )
    _OVERRIDES.clear()
    _OVERRIDES.update(new_dict)
    if not quiet:
        log.info("settings_overrides.loaded", count=len(_OVERRIDES))
    return new_dict


async def refresh_from_db(db: AsyncSession) -> bool:
    """Reload the dict from the table; True if anything actually changed.

    Callers should ``get_settings.cache_clear()`` when this returns True
    so the next Settings read picks up the new values.
    """
    before = dict(_OVERRIDES)
    after = await load_from_db(db, quiet=True)
    changed = after != before
    if changed:
        changed_keys = sorted(
            k for k in (set(before) | set(after)) if before.get(k) != after.get(k)
        )
        log.info("settings_overrides.refreshed", changed=changed_keys)
    return changed


async def upsert(
    db: AsyncSession,
    *,
    name: str,
    value: Any,
    actor_label: str = "admin",
) -> None:
    """Persist + register a single override. Caller commits."""
    encoded = json.dumps(value)
    stmt = (
        insert(AppSettingOverride)
        .values(name=name, value=encoded, actor_label=actor_label)
        .on_conflict_do_update(
            index_elements=["name"],
            set_={"value": encoded, "actor_label": actor_label},
        )
    )
    await db.execute(stmt)
    _OVERRIDES[name] = value
    log.info("settings_overrides.set", name=name, actor=actor_label)


async def remove(db: AsyncSession, *, name: str) -> bool:
    """Drop an override (revert to env-defined default). Returns True if
    a row was actually deleted. Caller commits."""
    result = await db.execute(delete(AppSettingOverride).where(AppSettingOverride.name == name))
    _OVERRIDES.pop(name, None)
    deleted = bool(result.rowcount)
    if deleted:
        log.info("settings_overrides.removed", name=name)
    return deleted
