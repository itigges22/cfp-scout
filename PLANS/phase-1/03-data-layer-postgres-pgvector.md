# 03 — Data Layer: Postgres + pgvector

## Goal
Bring up Postgres 16 with `pgvector` and supporting extensions, persistent
volume, healthcheck, and the connection pattern the API uses.

## Prereqs
- 02 (compose)

## Tasks
- [ ] Base image: **`pgvector/pgvector:pg16`**.
- [ ] Compose service `postgres`:
  - Named volume `postgres_data` at `/var/lib/postgresql/data`.
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` from `.env` (no defaults).
  - Port 5432 not exposed in `compose.yaml`; `compose.override.dev.yaml` exposes it.
  - Healthcheck: `pg_isready -U $POSTGRES_USER`.
  - Dev tuning: `shared_buffers=256MB`, `work_mem=8MB`.
- [ ] `infra/postgres/init/01-extensions.sql` mounted to
      `/docker-entrypoint-initdb.d/`:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE EXTENSION IF NOT EXISTS unaccent;
  CREATE EXTENSION IF NOT EXISTS pgcrypto;
  ```
- [ ] Logical separation via **schemas**:
  - `app` — application tables
  - `vectors` — embedding tables
  - `audit` — append-only audit + content versioning
  - `jobs` — APScheduler jobstore (step 13)
- [ ] Connection string in `DATABASE_URL`. Document the format in `.env.example`.
- [ ] Roles:
  - `app` role used by the API (least privilege, no DDL outside migrations)
  - `app_audit` role with INSERT-only + SELECT on `audit` schema
  - The Postgres superuser stays internal; never used by the running app
- [ ] Backups:
  - `make db-dump` → `pg_dump` to `./backups/<timestamp>.sql.gz`.
  - `make db-restore FILE=...` → `pg_restore`.

## Security notes
- Postgres credentials only in `.env`.
- Postgres bound to compose network only.
- `app` role is the only role the api uses; cannot DELETE from `audit_log`.
- Init SQL applied once at first boot; subsequent schema changes go through Alembic.

## Acceptance criteria
- [ ] `make up postgres` → service healthy in < 15s.
- [ ] `psql` into the container shows all four extensions installed.
- [ ] `make db-dump && make nuke && make up && make db-restore` round-trips.
- [ ] api container connects with `postgres://app:...@postgres:5432/scout`.

## Open questions for the user
- **Backup retention** — keep 7 daily dumps locally? Drives Makefile rotation.

## Risks
- pgvector index choice (HNSW vs IVFFlat) affects latency. Locked in step 11
  once we know expected corpus size.
