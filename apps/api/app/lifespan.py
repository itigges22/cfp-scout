"""FastAPI lifespan hook — startup and shutdown.

Plan 06 wires:
  * DB connectivity check (fail loud if Postgres unreachable)
  * Settings dump at startup (redacted by structlog's redact processor)

Plan 13 will add:
  * APScheduler start/stop

Plan 12 will add:
  * Docling model warm-up (load layout models so first PDF upload doesn't pay the cost)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from sqlalchemy import text

from app.db.session import dispose_engine, get_engine
from app.settings import get_settings

log = structlog.get_logger("scout.lifespan")


def _redacted_settings_dump(settings) -> dict[str, object]:
    """Pydantic ``model_dump`` minus the SecretStr surfaces.

    Logged at startup so misconfiguration ("why isn't this connecting?") is
    one log entry away. SecretStrs are redacted by Pydantic itself — they
    show as ``**********`` when dumped.
    """
    return settings.model_dump(mode="json")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Yielded once per app boot. Startup before yield; shutdown after."""
    settings = get_settings()
    log.info("scout.starting", config=_redacted_settings_dump(settings))

    # Probe the DB. Failing here means the api refuses to come up if Postgres
    # is down, which is what the compose healthcheck contract expects.
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("scout.db_ok")
    except Exception as exc:
        log.error("scout.db_unreachable", error=str(exc))
        # Re-raise so uvicorn exits non-zero and compose restarts us.
        raise

    yield

    # Shutdown
    log.info("scout.shutting_down")
    await dispose_engine()
