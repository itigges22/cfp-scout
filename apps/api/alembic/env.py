"""Async-aware Alembic environment.

Alembic runs as the Postgres SUPERUSER (POSTGRES_USER from .env), not as
the limited `app` role the api uses for queries. DDL needs superuser
privileges; the role separation is intentional (see ADR-0002 + plan 03).

DSN is built at runtime from POSTGRES_* env vars — never hard-coded in
alembic.ini.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from app.db.base import Base
from app.settings import get_settings
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Import all model modules so Base.metadata sees every table.
# ---------------------------------------------------------------------------
# Models land in plan 06 pass 2. For now the import is a no-op (no models
# defined yet), but the wiring is in place so once models exist Alembic
# autogenerate sees them.
try:
    from app.db import models  # noqa: F401  -- triggers model registration
except ImportError:
    # Pass 2 hasn't shipped yet; that's fine. Alembic still runs (no-op).
    pass

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
target_metadata = Base.metadata


def _set_url() -> None:
    """Inject the runtime DSN into Alembic's config.

    We use the SUPERUSER sync DSN here because:
      * Alembic operates synchronously by default; the async path below
        adapts it.
      * DDL requires superuser privileges (CREATE SCHEMA, CREATE EXTENSION,
        etc.). The `app` role can't do those.
    """
    config.set_main_option("sqlalchemy.url", settings.superuser_sync_dsn)


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection.

    Useful for ``alembic upgrade head --sql`` to inspect what would run.
    """
    _set_url()
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,  # we use schemas; autogenerate must see them
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Sync function called inside the async engine context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema="public",
        compare_type=True,  # detect column type changes
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _async_main() -> None:
    """Wrap the sync migration runner in an async engine."""
    _set_url()
    # Async engine flavor — we ride asyncpg here too so the same driver is
    # used everywhere. Even though Alembic's run is essentially sync, this
    # keeps the dep surface minimal (one Postgres driver, asyncpg).
    config.set_main_option(
        "sqlalchemy.url",
        # Swap to asyncpg by default; psycopg fallback would also work.
        settings.superuser_async_dsn,
    )
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # short-lived; no need to keep idle conns
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Standard 'alembic upgrade head' codepath."""
    asyncio.run(_async_main())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
