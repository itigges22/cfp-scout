---
adr: "0002"
title: Logical separation via Postgres schemas, not multiple databases
status: accepted
date: 2026-05-21
supersedes: ""
superseded_by: ""
---

# 0002 — Logical separation via Postgres schemas, not multiple databases

## Context

Scout's data divides naturally into four groups:

- **Application tables** — conferences, sources, smes, audiences, messaging, matches, decisions, junctions
- **Vectors** — embedding chunks (pgvector + HNSW), kept separate so vacuum/reindex don't fight the OLTP hot path
- **Audit** — append-only `audit_log` and `content_versions`; written on every change, never updated
- **Jobs** — APScheduler `SQLAlchemyJobStore` persistence

We could split these along three boundaries:

1. One database, one schema (all tables together)
2. One database, multiple **schemas** (Postgres logical namespaces)
3. Multiple **databases** (e.g. `scout`, `scout_audit`, `scout_jobs`)

## Decision

**One database, four schemas: `app`, `vectors`, `audit`, `jobs`.**

Each schema gets distinct grants on the `app` role (the runtime role the api
connects as). In particular, `audit` is INSERT + SELECT only — UPDATE and
DELETE are not granted, enforcing the append-only invariant at the DB level.

## Consequences

**Positive**
- **Cross-schema joins work natively.** We can join `app.conferences` with
  `vectors.document_chunks` on `owner_id` in a single SQL query — no
  cross-DB shenanigans. The matcher and graph layer both rely on this.
- **One connection pool.** No need to maintain separate connections per
  DB. SQLAlchemy uses a single engine.
- **One Alembic migration history.** All schema changes ordered together.
- **One backup file.** `pg_dump --schema-only` and `pg_dump` work as you'd
  expect; restore is `psql` + a single file.
- **Permissions are still granular.** Schema-level grants give us the
  defense-in-depth we wanted (audit is append-only because the role can't
  do anything else there).

**Negative**
- A misconfigured grant could let the api write to `audit_log`. Mitigated
  by the explicit absence of UPDATE/DELETE in `ALTER DEFAULT PRIVILEGES`,
  plus an integration test that verifies the role can't mutate audit rows.
- One schema's heavy writes (e.g. `vectors` during a reindex) can affect
  the same database's autovacuum. We accept this for Phase 1's scale.
- Cannot do per-database tuning (e.g. different `shared_buffers` for OLTP
  vs vector workloads). Not a real constraint at our scale.

**Neutral**
- If we ever need to physically separate `vectors` (e.g. onto a different
  disk, or a different server), Postgres supports moving a schema's
  tablespace. Doable later if needed.

## Alternatives considered

- **One schema (`public`)** — Lost because: no defense-in-depth for the
  append-only audit invariant; everything mixed in `\d` output; harder
  to reason about.
- **Multiple databases** — Lost because: cross-DB queries require either
  `dblink` (gross) or application-level joins (slow). One connection pool
  becomes four. Backups become four files. Migration history becomes
  multiple Alembic chains. Operational overhead for zero real benefit at
  our scale.
- **Per-tenant schemas** — Not relevant; we're single-user.

## References

- `infra/postgres/init/02-roles-and-schemas.sql` — implementation
- `docs/ops/database.md` — operator-facing description
- [plan 03](../../PLANS/phase-1/03-data-layer-postgres-pgvector.md) — design
- [plan 04](../../PLANS/phase-1/04-database-schema.md) — table-level details
