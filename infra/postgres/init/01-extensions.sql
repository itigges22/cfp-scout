-- Scout — Postgres initialization (extensions).
--
-- The Postgres container runs every *.sql file in this directory ONCE,
-- on first boot, against the default database. To re-run, `make nuke && make up`.
--
-- Full schema design (roles, schemas, tables) lives in plans 03 + 04 + 06.
-- This file installs the Postgres extensions every plan downstream relies on.

CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector for embeddings (step 11)
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- fuzzy dedup on conference names (step 15)
CREATE EXTENSION IF NOT EXISTS unaccent;   -- accent-insensitive matching (step 15)
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid() for primary keys
