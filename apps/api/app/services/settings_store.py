"""Operator settings: the override store, and how it reaches every process.

WHAT THIS DOES
    Settings normally come from environment variables. This lets an
    operator override any of them from the admin UI instead: overrides
    live one row per name, are loaded into an in-memory dict at startup,
    and a PATCH writes through to both then clears the settings cache.

    The refresh loop re-reads that table on an interval so a change made
    on one API replica reaches its siblings and the standalone scheduler
    without a restart.

HOW IT CONNECTS
    Called by   app/lifespan.py and app/scheduler_standalone.py (load at
                startup, start/stop the loop), api/v1/admin_settings.py
                (write), app/settings.py (reads the dict when resolving
                any field), app/maintenance.py, api/v1/diagnostics.py
    Reads/writes app.app_setting_overrides
    Tuning      settings.settings_refresh_seconds

WORTH KNOWING
    These were two modules, and the package docstring argued they must
    stay apart because one is data access and the other an asyncio task.
    They are one concept — an override that does not propagate is not an
    override — and the loop is thirty lines around a call to the store
    directly below it.

    The refresh only INVALIDATES caches; it does not push values anywhere.
    Consumers must re-read on use for this to work.

    NOT a general key-value store: upsert() rejects any name not
    registered in settings_spec.SPECS. Operational state nobody configures
    goes in services/diagnostics.py.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSettingOverride

log = structlog.get_logger("scout.settings_store")


# ==========================================================================
# py
# ==========================================================================


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


async def load_from_db(db: AsyncSession, *, quiet: bool = False) -> dict[str, Any]:
    """Populate the in-memory dict from the table.

    Called once at startup and then periodically by the refresh loop
    (``app.services.settings_store``) so overrides written by another
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
                "bad_json",
                name=row.name,
                value=row.value[:80],
            )
    _OVERRIDES.clear()
    _OVERRIDES.update(new_dict)
    if not quiet:
        log.info("loaded", count=len(_OVERRIDES))
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
        log.info("refreshed", changed=changed_keys)
    return changed


def _reject_unknown(name: str) -> None:
    """Raise unless ``name`` is a registered, operator-editable setting."""
    # Deferred: app.settings imports THIS module, so a module-level
    # import of settings_spec (which imports app.settings) would cycle.
    from app.settings import SPECS

    known = {spec.name for spec in SPECS}
    if name not in known:
        raise ValueError(
            f"{name!r} is not a registered setting. app_setting_overrides "
            f"stores operator-editable settings only — add a SettingSpec "
            f"for it, or keep the value somewhere that is not the settings "
            f"table."
        )


async def upsert(
    db: AsyncSession,
    *,
    name: str,
    value: Any,
    actor_label: str = "admin",
) -> None:
    """Persist + register a single override. Caller commits.

    ``name`` must be a setting registered in settings_spec.SPECS. This
    table is for operator-editable SETTINGS, and without the check it
    quietly became a general key-value store — ``diagnostics.py`` was
    parking a "when did someone last clear the error list" timestamp in
    it, which is operational state and not a setting anyone configures.

    That matters beyond tidiness. ``get_settings()`` builds a Settings
    object from these rows; a key that is not a Settings field is dead
    weight at best, and a typo'd real key ("mach_m_gate") would sit in
    the table looking configured while changing nothing.
    """
    _reject_unknown(name)
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
    log.info("set", name=name, actor=actor_label)


async def remove(db: AsyncSession, *, name: str) -> bool:
    """Drop an override (revert to env-defined default). Returns True if
    a row was actually deleted. Caller commits."""
    result = await db.execute(delete(AppSettingOverride).where(AppSettingOverride.name == name))
    _OVERRIDES.pop(name, None)
    deleted = bool(result.rowcount)
    if deleted:
        log.info("removed", name=name)
    return deleted


# ==========================================================================
# settings_refresh.py
# ==========================================================================


_task: asyncio.Task | None = None


async def _refresh_once() -> None:
    # Imported here, not at module scope: app/settings.py imports this
    # module to resolve overrides, and app/db/session.py imports settings.
    # At module scope that is a cycle; only the refresh loop needs a
    # session, and it runs long after both are loaded.
    from app.db.session import get_session_factory
    from app.settings import get_settings

    async with get_session_factory()() as session:
        changed = await refresh_from_db(session)
    if changed:
        get_settings.cache_clear()


async def _loop() -> None:
    from app.settings import get_settings

    while True:
        # Re-read the interval each cycle so it is itself tunable.
        interval = get_settings().settings_refresh_seconds
        if interval <= 0:
            # Disabled — park and re-check occasionally in case an
            # operator re-enables it (that change arrives via env/restart
            # or a PATCH handled by this same process).
            await asyncio.sleep(60)
            continue
        await asyncio.sleep(interval)
        try:
            await _refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("settings_refresh.failed", error=str(exc))


def start_refresh_task() -> None:
    """Idempotent; call once per process after the initial overrides load."""
    from app.settings import get_settings

    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.get_running_loop().create_task(_loop(), name="settings-refresh")
    log.info(
        "settings_refresh.started",
        interval_seconds=get_settings().settings_refresh_seconds,
    )


async def stop_refresh_task() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with suppress(asyncio.CancelledError):
        await _task
    _task = None
    log.info("settings_refresh.stopped")
