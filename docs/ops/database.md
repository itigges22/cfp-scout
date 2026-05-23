# Database layout and operations

This runbook describes Scout's Postgres setup: schemas, roles, extensions,
and how to debug it. Refers to the `postgres` container in `infra/compose/compose.yaml`.

For backups specifically, see [`backups.md`](backups.md).

## At a glance

- **Image**: `pgvector/pgvector:pg16`
- **Database**: one database (name from `POSTGRES_DB` in `.env`)
- **Schemas**: four logical schemas — `app`, `vectors`, `audit`, `jobs`
- **Roles**: superuser (`POSTGRES_USER` from `.env`) for DDL + migrations; `app` for runtime queries
- **Volume**: named volume `postgres_data` mounted at `/var/lib/postgresql/data`
- **Port**: not published to the host by default (compose-network only). `make up-dev` exposes 5432 on `127.0.0.1`.
- **Init SQL**: `infra/postgres/init/*.sql` runs on first boot, in file-order

## Schemas

| Schema | Purpose | Why separate |
|--------|---------|--------------|
| `app` | Application tables: conferences, sources, smes, audiences, messaging, matches, junctions | The OLTP hot path. Most reads/writes target here. |
| `vectors` | Embedding storage (pgvector) | HNSW indexes are expensive to rebuild; separating the schema means vacuum + reindex don't fight the hot OLTP tables. |
| `audit` | Append-only `audit_log` and `content_versions` | Write-heavy and grow-forever. App role has INSERT + SELECT only — UPDATE/DELETE forbidden at the role level (defense in depth). |
| `jobs` | APScheduler `SQLAlchemyJobStore` | Background jobs persist here so they survive container restarts without Redis (see plan 13). |

See [ADR-0002](../ADR/0002-postgres-schemas-not-databases.md) for the rationale on schemas vs separate DBs.

## Roles

There are two roles you'll interact with.

### `POSTGRES_USER` (superuser)
- Username + password come from `.env` (`POSTGRES_USER` / `POSTGRES_PASSWORD`).
- Owns the database. Used by Alembic for migrations (plan 06).
- **Do not use this role for runtime app queries.** It can do anything; bugs become catastrophic.

### `app`
- Created by `infra/postgres/init/02-roles-and-schemas.sql`.
- Username `app`, password `app` (placeholder; rotate via `ALTER ROLE app PASSWORD '...';` if your threat model requires).
- This is the role the running api connects as (wired in plan 06 via the `DATABASE_URL` env var).
- Permissions:
  - `app`, `vectors`, `jobs` schemas: SELECT + INSERT + UPDATE + DELETE on all tables (via default privileges; applies to tables created later by Alembic too)
  - `audit` schema: SELECT + INSERT only. **Never UPDATE/DELETE** — enforces the append-only invariant at the DB level.

### Why two roles
The `app` role's limited permissions are a defense-in-depth measure. If a SQL-injection bug or a misbehaving service ever tries to mutate `audit_log`, Postgres rejects it. The app code never has the power to silently rewrite history.

## Extensions

Loaded by `infra/postgres/init/01-extensions.sql` on first boot:

| Extension | Used for |
|-----------|----------|
| `vector` | pgvector — embedding storage + HNSW index (plan 11) |
| `pg_trgm` | Fuzzy name match for dedup (plan 15) and trigram indexes |
| `unaccent` | Accent-insensitive matching (plan 15) |
| `pgcrypto` | `gen_random_uuid()` for primary keys |

No Apache AGE — the knowledge graph is computed in-memory with NetworkX (plan 16, [ADR-0001](../ADR/0001-route-1-local-install-2-containers.md)).

## Connection strings

The compose file constructs the runtime URL automatically:

```
postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
```

That's what `DATABASE_URL` resolves to inside the api container. For now (plans 02-05) it uses the superuser; **plan 06 switches the api's runtime connection to the `app` role** while keeping the superuser for Alembic migrations.

For connecting from your host (after `make up-dev`):

```
postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}
```

## Commands

```bash
make up                # bring postgres + api up
make up-dev            # same + expose postgres on 127.0.0.1:5432
make db-psql           # open a psql shell inside the container
make db-dump           # snapshot to ./backups/scout-<timestamp>.sql.gz
make db-restore FILE=./backups/scout-...sql.gz
make nuke              # destroy the postgres volume (prompts to confirm)
```

## Init SQL ordering

Files in `infra/postgres/init/` run in lexicographic order on first boot:

1. `01-extensions.sql` — pgvector, pg_trgm, unaccent, pgcrypto
2. `02-roles-and-schemas.sql` — schemas + the `app` role + default privileges

Add new init SQL with a higher prefix (`03-...`, `04-...`) to keep ordering predictable.

**These files do NOT run on subsequent boots.** If you change them, run `make nuke && make up` to re-apply (destroys the volume).

## Troubleshooting

### "permission denied for schema app" when the api queries the DB
The `app` role doesn't have access to the table you're querying. Check:

```sql
\dn+   -- list schemas with privileges
\dp app.<table>   -- list table-level privileges
```

If the table was created outside the default-privileges path (e.g. by a Postgres extension), grant explicitly in a migration:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON app.<table> TO app;
```

### "role 'app' does not exist"
The init SQL didn't run. This happens when you mount the `postgres_data` volume from a pre-init-SQL state. Fix: `make nuke && make up`.

### Healthcheck fails on first boot
Init SQL is still running. The `start_period: 10s` healthcheck grace should cover it; bump higher in compose if your machine is slow.

### pgvector queries are slow
Either the HNSW index doesn't exist (plan 11 creates it) or `EXPLAIN ANALYZE` shows a sequential scan. Verify with:

```sql
\d+ vectors.document_chunks
EXPLAIN ANALYZE SELECT ... FROM vectors.document_chunks ORDER BY embedding <=> '[...]' LIMIT 10;
```

### Container won't start: "directory not empty"
The data volume has data but the env vars don't match. Postgres init only runs against an empty data directory. Either restore matching env, or `make nuke` if you don't need the data.

## See also

- [`../data-model.md`](../data-model.md) — full ERD + per-table notes
- [`migrations.md`](migrations.md) — Alembic workflow
- [`backups.md`](backups.md) — dump / restore
- [ADR-0002](../ADR/0002-postgres-schemas-not-databases.md) — schema separation rationale
- [ADR-0004](../ADR/0004-async-sqlalchemy-and-alembic.md) — async SQLAlchemy + Alembic
