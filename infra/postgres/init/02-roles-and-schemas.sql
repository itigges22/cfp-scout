-- Scout — roles and schemas.
--
-- Runs once on first boot of the postgres container, after 01-extensions.sql.
-- To re-run: `make nuke && make up` (destroys the volume).
--
-- See docs/ops/database.md for the design rationale.

-- ============================================================================
-- Schemas
-- ============================================================================
-- Logical separation in one database. Cheaper than separate databases and
-- lets us run cross-schema queries (e.g. join app.conferences with
-- vectors.document_chunks). See ADR-0002.

CREATE SCHEMA IF NOT EXISTS app;
COMMENT ON SCHEMA app IS
    'Application tables: conferences, sources, smes, audiences, messaging, '
    'matches, junction tables, etc. Most reads + writes target this schema.';

CREATE SCHEMA IF NOT EXISTS vectors;
COMMENT ON SCHEMA vectors IS
    'Embedding storage (pgvector). Separate schema isolates HNSW index '
    'vacuum/reindex costs from the hot OLTP path.';

CREATE SCHEMA IF NOT EXISTS audit;
COMMENT ON SCHEMA audit IS
    'Append-only audit_log and content_versions. The app role has INSERT + '
    'SELECT only on these tables — UPDATE/DELETE are revoked at the role '
    'level as defense in depth against application bugs.';

CREATE SCHEMA IF NOT EXISTS jobs;
COMMENT ON SCHEMA jobs IS
    'APScheduler SQLAlchemyJobStore (plan 13). Persisting jobs here means '
    'they survive container restarts without needing Redis.';

-- ============================================================================
-- Roles
-- ============================================================================
-- POSTGRES_USER (set via .env) is the superuser and DDL owner. The running
-- API does NOT use it for queries.
--
-- The `app` role is what the api connects as at runtime (wired in plan 06).
-- It can read/write app + vectors + jobs, but only INSERT + SELECT on audit.
--
-- For Phase 1 (local install, single user), the `app` role's password is a
-- placeholder. Postgres is only reachable on the compose network — never on
-- the host or the public network — so this is acceptable. Rotate with
-- `ALTER ROLE app PASSWORD '...';` if your threat model demands it.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app') THEN
        CREATE ROLE app LOGIN PASSWORD 'app';
        COMMENT ON ROLE app IS
            'Runtime application role. Used by the api''s SQLAlchemy session. '
            'Per-schema grants below; per-table grants land in plan 04 '
            'migrations via Alembic.';
    END IF;
END$$;

-- USAGE on schemas: required even to reference objects inside.
GRANT USAGE ON SCHEMA app, vectors, jobs, audit TO app;

-- Default privileges: any table created LATER (by Alembic in plan 06, by
-- APScheduler in plan 13, etc.) gets the right perms automatically without
-- a per-table GRANT.

ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;
ALTER DEFAULT PRIVILEGES IN SCHEMA vectors
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;
ALTER DEFAULT PRIVILEGES IN SCHEMA jobs
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;

-- audit schema: INSERT + SELECT only. UPDATE/DELETE are NOT granted, so
-- attempts to mutate audit_log or content_versions from the app role fail
-- at the DB level.
ALTER DEFAULT PRIVILEGES IN SCHEMA audit
    GRANT SELECT, INSERT ON TABLES TO app;

-- Sequences: granted USAGE so SERIAL/IDENTITY columns work if we ever use
-- them. Most of our tables use uuid via gen_random_uuid() so this is mostly
-- belt-and-suspenders.
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT USAGE ON SEQUENCES TO app;
ALTER DEFAULT PRIVILEGES IN SCHEMA vectors
    GRANT USAGE ON SEQUENCES TO app;
ALTER DEFAULT PRIVILEGES IN SCHEMA jobs
    GRANT USAGE ON SEQUENCES TO app;

-- Future-proofing: when a table is created in a schema, queries against it
-- need SELECT/INSERT/etc on the table itself. The defaults above handle that
-- for new tables. If a table is created OUTSIDE these defaults (e.g. by an
-- extension), it needs an explicit GRANT in the migration that creates it.
