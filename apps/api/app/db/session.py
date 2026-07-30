"""The async engine, the session factory, and the FastAPI session dependency.

WHAT THIS DOES
    Builds one connection pool per process, lazily on first use, so
    importing a model does not require a running database (tests depend
    on that). Two ways to get a session:

      * ``DbSession`` -- the FastAPI dependency. A route annotates a
        parameter with it and gets a session scoped to the request.
      * ``get_session_factory()`` -- for code with no request behind it,
        chiefly background tasks and CLI maintenance.

    A session rolls back on exception and re-raises, so the connection
    returns to the pool clean and the error handler still sees the
    failure. ``dispose_engine`` tears the pool down at shutdown.

HOW IT CONNECTS
    Called by   all of app/api/v1/* via DbSession; all of app/tasks/* via
                get_session_factory; app/services/*; app/lifespan.py and
                app/scheduler_standalone.py (dispose on shutdown);
                app/maintenance.py
    Reads       every table, indirectly
    Helpers     app/settings.py for database_url
    Tuning      pool sizing is hard-coded here: pool_size=5,
                max_overflow=10 (15 connections max per process),
                pool_pre_ping, pool_recycle=1800s

WORTH KNOWING
    Fifteen connections per process is a hard ceiling. Code that fans out
    database-touching work must cap its own concurrency well below it --
    see the semaphore in tasks.py -- or every task blocks
    waiting on the pool.

    ``expire_on_commit=False`` keeps ORM objects readable after commit;
    ``autoflush=False`` means flushes are explicit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import Settings, get_settings

# ---------------------------------------------------------------------------
# Engine + session factory — created on first use
# ---------------------------------------------------------------------------
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(settings: Settings) -> AsyncEngine:
    """Construct the async engine.

    Pool sizing notes:
      * pool_size=5 + max_overflow=10 fits a single api process with
        --workers 2 comfortably. Bump if you ever scale workers.
      * pool_pre_ping=True catches stale connections from network blips
        (e.g. the postgres container restarting in the background).
      * pool_recycle=1800 (30 min) protects against very-long-lived
        connections going stale.
    """
    return create_async_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
        echo=False,  # set to True per-test for SQL log debugging
    )


def get_engine() -> AsyncEngine:
    """Return the singleton engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,  # keep ORM objects usable after commit
            autoflush=False,  # flushes are explicit; safer with async code
        )
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an :class:`AsyncSession`.

    The dependency context manages the session lifecycle. Routes obtain a
    session via ``Annotated[AsyncSession, Depends(get_db)]`` (use the
    :data:`DbSession` alias below).
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            # Don't swallow — let the global error handler turn it into a
            # problem+json response. Rolling back here keeps the session
            # clean for connection-pool reuse.
            await session.rollback()
            raise


# Convenience type alias for route signatures.
# ``def list_things(db: DbSession): ...``  reads cleaner than the verbose form.
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def dispose_engine() -> None:
    """Tear down the engine. Called from the FastAPI lifespan on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
