---
adr: "0004"
title: Async SQLAlchemy 2.x + Alembic for the data access layer
status: accepted
date: 2026-05-21
supersedes: ""
superseded_by: ""
---

# 0004 — Async SQLAlchemy 2.x + Alembic for the data access layer

## Context

Scout's api is fully async (FastAPI). The data access layer needs to fit
that model without blocking the event loop on DB calls. Three things to
decide:

1. **Sync vs async DB driver**
2. **ORM choice (SQLAlchemy vs alternative)**
3. **Migration tooling (Alembic vs alternative)**

The PDF only specifies "Postgres" so the rest is our call.

## Decision

- **Async** — use SQLAlchemy 2.x's native async support with `asyncpg` as the driver.
- **SQLAlchemy 2.x** — the ORM. New `DeclarativeBase` + `Mapped[...]` + `mapped_column` style, not the legacy 1.x patterns.
- **Alembic** — migrations. Configured async via `async_engine_from_config`.
- **Role separation** — Alembic runs as the Postgres superuser (so it has DDL privileges); the api proper runs as the limited `app` role (per [ADR-0002](0002-postgres-schemas-not-databases.md)).

## Consequences

**Positive**
- **Non-blocking DB.** A slow query doesn't starve other request handlers. Critical because we're going to do embedding similarity searches that take ~10-100ms each.
- **Type safety.** SQLAlchemy 2.x's `Mapped[...]` annotations let mypy catch column-type mismatches at the application boundary.
- **Naming convention** baked into `metadata` means Alembic autogenerate produces deterministic constraint names; no churn on every regeneration.
- **One driver, asyncpg, used everywhere** — the api at runtime and Alembic during migrations. Less surface area.

**Negative**
- **Setup ceremony.** Async Alembic is more involved than the sync default (requires `async_engine_from_config` + `connection.run_sync(...)`). Done once in `alembic/env.py`; forget about it.
- **Async ORM has sharper edges.** Specific footguns: `expire_on_commit=False` is needed or session-bound objects detach after every commit. `autoflush=False` so we don't trigger surprise flushes mid-await. Both configured in `apps/api/app/db/session.py`.
- **Tests need an event loop.** Configured via `asyncio_mode = "auto"` in `pyproject.toml`; pytest-asyncio handles it.

**Neutral**
- Sync DB libraries (e.g. one-off scripts) can still use the same SQLAlchemy models via a separate sync engine — the `Base` is async-agnostic.

## Alternatives considered

- **Sync SQLAlchemy + `psycopg`** — Would block the event loop on every query. Workarounds (`run_in_threadpool`) defeat the point of async in the first place.
- **SQLModel** (Pydantic + SQLAlchemy) — Tempting because schemas and models could share definitions. Rejected because SQLModel is still pre-1.0, has rough edges around async + complex relationships, and our input-validation schemas (see `apps/api/app/schemas/`) have intentionally different shapes from the DB tables (e.g. SME wizard validates a UUID list, the DB stores a junction).
- **Tortoise ORM** — Async-first ORM. Considered but loses SQLAlchemy's ecosystem (Alembic, type stubs, broader query API). Not worth the trade.
- **Raw asyncpg + hand-written SQL** — Considered for the embedding path specifically (vector ops are clearer in raw SQL). We can still drop to raw SQL inside an SQLAlchemy session for those queries; no need to commit the whole project to raw SQL.
- **`yoyo-migrations` / `migra` instead of Alembic** — Alembic is the SQLAlchemy ecosystem default. Autogenerate isn't perfect but it's good enough for our scale; reviewing the generated migration before commit is mandatory anyway.

## Implementation

- **Base + naming convention**: `apps/api/app/db/base.py`
- **Engine + session factory**: `apps/api/app/db/session.py` (`get_db` FastAPI dep + `DbSession` Annotated alias)
- **Models**: `apps/api/app/db/models/*` (land in plan 06 pass 2)
- **Alembic**: `apps/api/alembic.ini` + `apps/api/alembic/env.py` (async-aware) + `apps/api/alembic/script.py.mako`
- **Makefile**: `make migrate`, `make migrate-create MSG=...`, `make migrate-history`, `make migrate-current`
- **Settings**: `apps/api/app/settings.py` — `database_url` is the app-role DSN; `superuser_*_dsn` properties built from `POSTGRES_*` env vars for Alembic only

## References

- [SQLAlchemy 2.0 async docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic async cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic)
- [ADR-0002](0002-postgres-schemas-not-databases.md) — schema separation + role rationale
- [`docs/ops/migrations.md`](../ops/migrations.md) — operator runbook
- [`docs/data-model.md`](../data-model.md) — full schema + per-table notes
