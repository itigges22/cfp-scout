"""Async-aware Alembic environment.

Alembic connects as the Postgres SUPERUSER (POSTGRES_USER), not the limited
``app`` role the API uses for queries — DDL needs privileges the app role
deliberately lacks. See ADR-0002 for the role split.

The DSN is built at runtime from POSTGRES_* env vars, never hard-coded in
alembic.ini.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context

# Importing the models package registers every table on Base.metadata,
# which is what autogenerate diffs against.
from app.db import models  # noqa: F401
from app.db.models import Base
from app.settings import get_settings
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

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


# ---------------------------------------------------------------------------
# Autogenerate safety filter
# ---------------------------------------------------------------------------
# ``include_schemas=True`` is required (the app spans app/vectors/audit/jobs),
# and without a companion filter autogenerate proposes DROPping every object
# it can see but cannot find in Base.metadata.
#
# Two things are owned by other systems and must never be managed here:
#   * schema ``jobs``  — APScheduler creates and migrates its own table.
#   * the HNSW index   — created by raw SQL in the initial migration because
#                        Alembic cannot express pgvector's operator class or
#                        its m / ef_construction parameters.
#
# Do NOT set ``version_table_schema``: ``public`` is already the default, and
# naming it explicitly stops Alembic matching its own exclusion (which
# compares against None), so it proposes dropping ``alembic_version``.
_UNMANAGED_SCHEMAS = {"jobs"}
_UNMANAGED_INDEXES = {"ix_document_chunks_embedding_hnsw"}


def _include_object(obj, name, type_, reflected, compare_to):
    """Return False for objects Alembic must not try to manage."""
    if getattr(obj, "schema", None) in _UNMANAGED_SCHEMAS:
        return False
    return not (type_ == "index" and name in _UNMANAGED_INDEXES)


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
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


# Session-level advisory lock so concurrent ``alembic upgrade head`` runs
# serialize instead of racing.
#
# The Helm chart runs migrations as an init container on EVERY api replica
# (deploy/helm/scout/templates/api-deployment.yaml, replicas: 2, HPA to 5),
# so a fresh install starts several upgrades against an empty database at
# once. Alembic has no built-in migration lock.
#
# Distinct from the scheduler's leader lock in app/scheduler.py.
_MIGRATION_LOCK_KEY = 0x5C000168


def _do_run_migrations(connection: Connection) -> None:
    """Sync function called inside the async engine context."""
    # Blocks (does not fail) until any other migrating process finishes.
    #
    # The commit() is load-bearing: exec_driver_sql opens an implicit
    # transaction, and Alembic's own commit would nest inside it, so the
    # upgrade would roll back on connection close. pg_advisory_lock is
    # SESSION-scoped, so committing frees the transaction without releasing
    # the lock — it is held until this connection closes.
    connection.exec_driver_sql(
        f"SELECT pg_advisory_lock({_MIGRATION_LOCK_KEY})"
    )
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=_include_object,
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
