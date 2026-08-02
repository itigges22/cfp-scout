"""Integration test fixtures.

Spins up a real Postgres 16 + pgvector container via testcontainers,
runs Alembic migrations once per session, then yields httpx.AsyncClient
instances wired to the FastAPI app using the test DB.

Design:
  - One Postgres container for the whole test session (slow to start)
  - Alembic migrations run once per session via subprocess
  - Each test gets its own async engine + session (function-scoped)
  - clean_db fixture truncates tables before each test that needs it
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

import psycopg2  # type: ignore[import-untyped]
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

POSTGRES_IMAGE = "pgvector/pgvector:pg16"

# ---------------------------------------------------------------------------
# One container for the whole test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer(
        image=POSTGRES_IMAGE,
        username="scout",
        password="scoutdev",
        dbname="scout_test",
    ) as container:
        yield container


@pytest.fixture(scope="session")
def pg_sync_url(pg_container: PostgresContainer) -> str:
    """psycopg2 DSN."""
    raw = pg_container.get_connection_url()
    return raw.replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture(scope="session")
def pg_async_url(pg_container: PostgresContainer) -> str:
    """asyncpg DSN."""
    raw = pg_container.get_connection_url()
    return (
        raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        .replace("postgresql://", "postgresql+asyncpg://")
    )


# ---------------------------------------------------------------------------
# Schema bootstrap + Alembic migrations (once per session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def run_migrations(pg_container: PostgresContainer, pg_sync_url: str) -> None:
    """Create extensions + schemas + roles, then run alembic upgrade head."""
    import subprocess
    import sys

    # Bootstrap: replicate infra/postgres/init/01-extensions.sql + 02-roles-and-schemas.sql
    conn = psycopg2.connect(pg_sync_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    cur.execute("CREATE SCHEMA IF NOT EXISTS app;")
    cur.execute("CREATE SCHEMA IF NOT EXISTS vectors;")
    cur.execute("CREATE SCHEMA IF NOT EXISTS audit;")
    cur.execute("CREATE SCHEMA IF NOT EXISTS jobs;")
    cur.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app') THEN "
        "CREATE ROLE app LOGIN PASSWORD 'app'; END IF; END$$;"
    )
    cur.execute("GRANT USAGE ON SCHEMA app, vectors, jobs, audit TO app;")
    cur.execute("GRANT CREATE ON SCHEMA jobs TO app;")
    cur.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA app "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;"
    )
    cur.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA vectors "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;"
    )
    cur.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA jobs "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;"
    )
    cur.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT SELECT, INSERT ON TABLES TO app;"
    )
    cur.close()
    conn.close()

    # Inject env vars so alembic env.py + app.settings can read them
    host = pg_container.get_container_host_ip()
    port = str(pg_container.get_exposed_port(5432))
    os.environ["POSTGRES_USER"] = "scout"
    os.environ["POSTGRES_PASSWORD"] = "scoutdev"
    os.environ["POSTGRES_DB"] = "scout_test"
    os.environ["POSTGRES_HOST"] = host
    os.environ["POSTGRES_PORT"] = port
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://scout:scoutdev@{host}:{port}/scout_test"
    )
    # get_settings() is lru_cached: if any unit test touched it before this
    # fixture ran (combined `pytest tests/` runs), the cache holds the
    # placeholder DATABASE_URL (host "postgres") and every code path that
    # opens its own session — background tasks especially — dies on DNS.
    # Same for the memoized engine built from that stale settings object.
    from app.settings import get_settings

    get_settings.cache_clear()
    import app.db.session as _dbs

    _dbs._engine = None
    _dbs._session_factory = None

    # tests/integration/conftest.py -> tests/integration -> tests -> apps/api
    api_dir = str(Path(__file__).resolve().parents[2])
    env = {**os.environ, "PYTHONPATH": api_dir}
    # alembic/env.py calls get_settings() at import, so the migration
    # subprocess needs the non-DB settings too even though it never uses them.
    env.setdefault("LLM_BASE_URL", "https://llm.example.invalid/v1")
    env.setdefault("LLM_API_KEY", "sk-test-not-real")
    env.setdefault("SCRAPER_USER_AGENT", "Scout-Test/1.0")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic migration failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Sync psycopg2 connection fixture (for migration/constraint tests)
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg_conn(pg_sync_url: str, run_migrations: None):  # type: ignore[misc]
    """A synchronous psycopg2 connection for direct SQL in migration tests."""
    conn = psycopg2.connect(pg_sync_url)
    conn.autocommit = True
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Async engine (function-scoped to avoid event loop sharing issues)
# ---------------------------------------------------------------------------


@pytest.fixture()
async def test_engine(pg_async_url: str, run_migrations: None) -> AsyncGenerator[Any, None]:  # type: ignore[misc]
    """Function-scoped async engine — fresh event loop per test."""
    engine = create_async_engine(pg_async_url, echo=False, future=True)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Per-test async_client
# ---------------------------------------------------------------------------


@pytest.fixture()
async def async_client(  # type: ignore[misc]
    pg_async_url: str,
    run_migrations: None,
) -> AsyncGenerator[AsyncClient, None]:
    """httpx.AsyncClient pointing at FastAPI with the test DB."""
    from app.db.session import get_db
    from app.main import app

    engine = create_async_engine(pg_async_url, echo=False, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Truncation helper — wipes test data after each test
# ---------------------------------------------------------------------------


@pytest.fixture()
async def clean_db(pg_async_url: str, run_migrations: None) -> AsyncGenerator[None, None]:  # type: ignore[misc]
    """Truncate every app.* table before AND after the test.

    The table list is read from ``pg_tables`` rather than hardcoded, so it
    cannot drift out of step with the migrations. Truncating on the way in
    as well as out isolates a test from anything that ran before it,
    including tests that do not use this fixture.
    """
    engine = create_async_engine(pg_async_url, echo=False, future=True)

    async def _truncate() -> None:
        async with engine.begin() as conn:
            tables = (
                await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'app'"
                    )
                )
            ).scalars().all()
            if not tables:
                return
            qualified = ", ".join(f"app.{t}" for t in sorted(tables))
            await conn.execute(
                text(f"TRUNCATE {qualified} RESTART IDENTITY CASCADE")
            )

    await _truncate()
    yield
    await _truncate()
    await engine.dispose()
