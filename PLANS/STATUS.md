# Scout Phase 1 — Build Status

Single source of truth for build progress. Updated as each plan completes.

**Last updated:** 2026-05-21 (plan 09 backend complete; UI wizards land next)

## Plan status

Legend: ⬜ pending · 🚧 in progress · ✅ complete · ⏸️ blocked

| # | Plan | Status | Notes |
|---|------|--------|-------|
| 01 | Project bootstrap | ✅ | Completed 2026-05-21 |
| 02 | Containerization foundation | ✅ | Completed 2026-05-21. End-to-end `make up` not verified — neither Docker nor Podman installed on this build host. |
| 03 | Postgres + pgvector | ✅ | Completed 2026-05-21 |
| 04 | Database schema | ✅ | Design complete 2026-05-21; ORM + migrations land in plan 06 |
| 05 | Data input guardrails | ✅ | Completed 2026-05-21 |
| 06 | FastAPI skeleton | ✅ | Completed 2026-05-21 (infrastructure + ORM + baseline migration + seed) |
| 07 | Config & secrets | ✅ | Completed 2026-05-21. Implementation done in plan 06; this pass added the operator runbook. |
| 08 | Vite frontend skeleton | ✅ | Completed 2026-05-21 |
| 09 | Manual data entry | 🚧 | Backend CRUD landed 2026-05-21; UI wizards next pass |
| 10 | LLM service layer | ⬜ | |
| 11 | Embeddings & chunking | ⬜ | |
| 12 | PDF/RAG ingestion | ⬜ | |
| 13 | Background jobs (APScheduler) | ⬜ | |
| 14 | Web scraper | ⬜ | |
| 15 | Data validation & routing | ⬜ | |
| 16 | Knowledge graph | ⬜ | |
| 17 | Fit matcher algorithm | ⬜ | |
| 18 | SME matcher | ⬜ | |
| 19 | SME fit narrative | ⬜ | |
| 20 | Dashboard & review UI | ⬜ | |
| 21 | Graph exploration view | ⬜ | |
| 22 | Agent chat interface | ⬜ | |
| 23 | Conference series tracking | ⬜ | |
| 24 | CFP-closing digest | ⬜ | |
| 25 | Data lifecycle decay & versioning | ⬜ | |
| 26 | Observability & diagnostics | ⬜ | |
| 27 | Testing strategy | ⬜ | |
| 28 | CI/CD pipeline | ⬜ | |
| 29 | Security review & hardening | ⬜ | |
| 30 | Documentation & runbook | ⬜ | |
| 31 | Configuration workbook (XLSX) | ⬜ | |
| 32 | Multi-SME team recommendations | ⬜ | |
| 33 | Conference brief export | ⬜ | |

## Changelog

### 2026-05-21
- ✅ **Plan 01 — Project bootstrap** complete
  - `git init` with main branch
  - Monorepo layout: `apps/{api,web,scraper}`, `packages/shared-types`,
    `infra/{compose,containerfiles,postgres}`, `db/seeds`, `docs/{ADR,ops}`,
    `evals`, `.github/workflows`
  - Root files: `.gitignore`, `.gitattributes`, `LICENSE` (Apache 2.0),
    `README.md`, `Makefile`, `.python-version`, `.nvmrc`, `.pre-commit-config.yaml`
  - `Makefile` auto-detects docker compose vs podman compose; `make help` works
  - `apps/api/pyproject.toml` stub (ruff/mypy/pytest config; deps land in step 06)
  - `apps/web/package.json` stub (deps land in step 08)
  - `docs/ARCHITECTURE.md` skeleton with Mermaid diagram + glossary
  - `docs/ADR/0000-template.md` + `docs/ADR/0001-route-1-local-install-2-containers.md`
- ✅ **Plan 02 — Containerization foundation** complete
  - `infra/compose/compose.yaml` — 2-service stack (postgres + api)
    with healthchecks, depends_on, named volumes (`postgres_data`, `pdf_uploads`,
    `scraper_raw_pages`), single bridge network, resource limits
  - `infra/compose/compose.override.podman.yaml` — `:z` SELinux labels
  - `infra/compose/compose.override.dev.yaml` — host-bound Postgres port +
    `uvicorn --reload` + `LOG_FORMAT=console`
  - `infra/postgres/init/01-extensions.sql` — pgvector, pg_trgm, unaccent, pgcrypto
  - `apps/api/Containerfile` — 3-stage multi-stage build
    (spa-builder → py-builder → runtime), runs as non-root uid 1001, baked HEALTHCHECK
  - `apps/api/app/main.py` + `app/api/v1/health.py` — minimal FastAPI with
    `/api/v1/healthz`, OpenAPI at `/api/openapi.json`, StaticFiles at `/`
  - `apps/api/pyproject.toml` — fastapi + uvicorn deps added
  - `apps/web/index.html` — placeholder page (real Vite SPA lands in plan 08)
  - `.env.example` — all known env vars with sensible defaults (matcher
    weights, MaaS model names, safety classifier toggle, etc.)
  - **Verification status**: Docker/Podman not installed on this host;
    `make up` will need to be run on a host with one of them to confirm
    end-to-end. Python/JSON/Makefile syntax all check out locally.
- ✅ **Plan 03 — Postgres data layer** complete
  - `infra/postgres/init/02-roles-and-schemas.sql` — four schemas (`app`,
    `vectors`, `audit`, `jobs`); `app` role with role-level enforcement of
    the audit append-only invariant (INSERT + SELECT only on `audit`)
  - `Makefile` — `db-dump`, `db-restore`, `db-psql` wired up.
    `db-dump` writes to `./backups/scout-<ts>.sql.gz`;
    `db-restore` prompts to confirm (it's destructive)
  - `docs/ops/database.md` — operator runbook: schemas, roles, extensions,
    connection strings, init SQL ordering, troubleshooting
  - `docs/ops/backups.md` — backup/restore SOP including round-trip test
    pattern and a portable cross-host workflow
  - `docs/ADR/0002-postgres-schemas-not-databases.md` — decision record
    for schemas-over-databases
  - `docs/ARCHITECTURE.md` — updated postgres section to reflect actual
    role model and link to the new runbooks
- ✅ **Plan 04 — Database schema** (design phase) complete
  - `docs/data-model.md` — comprehensive schema reference: every table,
    column, index, conventions, Mermaid ERD, seed plan, open questions
  - `docs/ARCHITECTURE.md` — new "Data model" pointer section
  - **What's NOT here**: SQLAlchemy ORM models and the initial Alembic
    baseline migration. Those land in plan 06 (FastAPI skeleton), where
    Alembic gets wired up. Plan 04 is purely the design.
- ✅ **Plan 05 — Data input guardrails** complete
  - `apps/api/app/schemas/__init__.py` — package marker + intro doc
  - `apps/api/app/schemas/common.py` — `StrictBase` (sets `extra='forbid'`,
    `str_strip_whitespace=True`); StrEnums for role seniority,
    messaging source type, past-conference role + session type; ISO-3166-1
    and ISO-639-1 validators via `pycountry`; reusable `Annotated`
    type aliases (ShortTitle, AudienceName, ElevatorPitch, SmeBio, etc.)
  - `apps/api/app/schemas/messaging.py` — structured-source-only on create;
    PDF source goes through plan 12's upload endpoint
  - `apps/api/app/schemas/audience.py` — industry is freeform text now,
    validated against the team's industries vocabulary by the service layer
    (so adding a new industry is a workbook edit, not a code change)
  - `apps/api/app/schemas/sme.py` — 200-2000 char bio (forces real content);
    `external_links` constrained to `linkedin`/`github`/`website` keys only
  - `apps/api/app/schemas/past_conference.py` — single-row + CSV-row variants;
    CSV uses semicolon-separated `attended_by_names` (resolved by service layer)
  - `apps/api/app/schemas/topic.py` — admin-entry path; LLM-discovered
    topics use the same `name`/`aliases` rules but the service layer flags
    them `is_active=false, pending_review=true`
  - `docs/ops/data-guardrails.md` — operator runbook: what's rejected and why
  - `docs/ARCHITECTURE.md` — new "Input guardrails" section
  - `apps/api/pyproject.toml` — pydantic, pydantic-settings, email-validator,
    pycountry added to deps
  - All 7 schema files compile under py3.9 (syntax check; full validation
    happens once Pydantic is installed in the container build)
- 🚧 **Plan 06 — FastAPI backend skeleton** next (this is the big one:
  async SQLAlchemy + Alembic baseline migration encoding plan 04's design,
  structured logging, settings, OpenAPI schema, role switch-over to `app`)

### 2026-05-21 (plan 06 pass 1)
- 🚧 **Plan 06 — FastAPI skeleton, pass 1 of 2** complete (infrastructure)
  - `apps/api/app/settings.py` — full Pydantic-settings driven config matching
    plan 07's env contract. Rejects `LLM_API_KEY=changeme` and `POSTGRES_PASSWORD=changeme`
    placeholders. Validates matcher weights sum to 1.0. Exposes `superuser_sync_dsn`
    / `superuser_async_dsn` for Alembic use only.
  - `apps/api/app/logging.py` — structlog config with JSON or console renderer;
    redaction processor scrubs `api_key`, `password`, `token`, `secret`,
    `authorization` etc. plus bearer/sk-style patterns in string values.
  - `apps/api/app/db/base.py` — SQLAlchemy declarative `Base` with a project-wide
    naming convention so Alembic autogenerate produces deterministic constraint names.
  - `apps/api/app/db/session.py` — async engine + `AsyncSession` factory + `get_db`
    FastAPI dependency + `DbSession` Annotated alias. Pool sized for one api process.
  - `apps/api/app/middleware/request_id.py` — propagates `X-Request-ID` header and
    binds it into structlog contextvars; logs `request.completed` per request.
  - `apps/api/app/middleware/error_handler.py` — RFC 7807 problem+json responses
    for ValidationError, HTTPException, SQLAlchemyError, and the unhandled-Exception
    fallback. Tracebacks included only in `ENV=dev`.
  - `apps/api/app/lifespan.py` — startup probes the DB (`SELECT 1`) and fails loud
    if Postgres is unreachable; shutdown disposes the engine. Hooks reserved for
    APScheduler (plan 13) and Docling warm-up (plan 12).
  - `apps/api/app/main.py` — rewired to use the new lifespan + middleware + error
    handlers; CORS configured for the Vite dev server.
  - `apps/api/app/api/v1/health.py` — adds `/api/v1/readyz` that runs `SELECT 1`
    against the DB; returns 503 if unreachable.
  - `apps/api/alembic.ini` + `alembic/env.py` (async-aware) + `script.py.mako`
    template. Alembic uses the superuser DSN (built from POSTGRES_* env vars);
    api uses the limited `app` role.
  - `infra/compose/compose.yaml` — `DATABASE_URL` now uses the `app` role;
    POSTGRES_* env vars exposed to the api container so Alembic can build its
    own DSN. New `APP_DB_PASSWORD` env (default 'app').
  - `Makefile` — `make migrate`, `make migrate-create MSG=...`, `make migrate-history`,
    `make migrate-current` all wired up (run `alembic` inside the api container).
  - `.env.example` — `APP_DB_PASSWORD` documented; superuser-vs-app-role separation
    explained inline.
  - `apps/api/pyproject.toml` — sqlalchemy[asyncio], asyncpg, alembic, structlog,
    pgvector added to deps.
  - `docs/ADR/0004-async-sqlalchemy-and-alembic.md` — async SQLAlchemy + Alembic
    decision recorded; alternatives considered (sync, SQLModel, Tortoise, raw asyncpg).
  - `docs/ops/migrations.md` — operator runbook for daily migration workflow,
    common gotchas, role/schema interaction.
  - `docs/ARCHITECTURE.md` — ADR list updated.
  - **All Python compiles (py3.9 syntax check).** Container-side runtime
    validation when `make up` runs on a Docker/Podman host.
- ✅ **Plan 06 pass 2** complete (ORM + migrations + seed)
  - `apps/api/app/db/models/` — full SQLAlchemy 2.x ORM:
    - `_mixins.py` — `TimestampedMixin` + `uuid_pk()` helper
    - `entities.py` — 11 tables: MessagingDocument, AudienceProfile,
      StrategicPillar, Sme, Topic, ConferenceSeries, PastConference,
      Source, RawPage, Conference, ConferenceSource
    - `junctions.py` — 7 tables (the graph edges): ConferenceTopic,
      ConferenceAudience, ConferencePillar, ConferenceSme, SmeTopic,
      SmeAudience, MessagingPillar
    - `vectors.py` — DocumentChunk (pgvector + chunk_metadata jsonb +
      polymorphic owner_type/owner_id) + EmbeddingModel
    - `matching.py` — Match (with sme_fit_narratives), MatchTeamRecommendation
      (composite PK + team_size CHECK), Decision
    - `audit.py` — AuditLog, ContentVersion (no TimestampedMixin —
      append-only)
    - `ops.py` — IngestJob, LLMCall, ChatSession, ChatMessage, Notification
    - `__init__.py` — re-exports every model so Alembic autogenerate sees them
  - `apps/api/alembic/versions/20260521_1200_initial_baseline.py` —
    hand-crafted baseline (~600 lines) creating all 30 tables, indexes
    (including the partial index on conferences(status, start_date) and
    the HNSW index on document_chunks.embedding via raw SQL), FKs,
    CHECK constraints, server-side defaults.
  - `apps/api/alembic/versions/20260521_1210_seed_embedding_model.py` —
    inserts the `nomic-embed-text-v1-5` row.
  - `Makefile` — `make seed` now informational (seeds baked into Alembic)
  - `docs/ops/migrations.md` — history table populated with the two
    baseline revisions
  - `docs/data-model.md` — migration history section updated
  - **All 8 model files + both migrations compile under py3.9 (syntax check)**.
    Runtime validation pending Docker/Podman on a build host that can run
    `make migrate` against a live Postgres.
- ✅ **Plan 07 — Config & secrets** complete
  - Implementation already landed via plan 06's `app/settings.py` (validators
    + SecretStr fields), `app/logging.py` (redaction processor), and
    `app/lifespan.py` (startup banner with redacted config). `.env.example`
    has every documented env var. `.gitignore` blocks `.env*` while allowing
    `.env.example`. gitleaks is wired into `.pre-commit-config.yaml` from plan 01.
  - **New in this pass**: `docs/ops/secrets.md` — operator runbook covering:
    what counts as a secret in Scout, where each lives, first-time setup,
    MaaS key provisioning, MaaS rotation procedure (revoke-last to avoid
    breaking in-flight requests), Postgres password rotation (easy nuke vs
    surgical ALTER USER paths), leak-response playbook (revoke → audit →
    find leak → if-committed-rewrite-history → post-incident), and the
    seven-layer defense recap.
  - `docs/ARCHITECTURE.md` — new "Secrets" section linking to the runbook.
  - **Manual sanity check**: grep across all committed files found zero
    secret-shaped patterns outside docs and `.env.example` placeholders.
    `.env` confirmed gitignored.
- ✅ **Plan 08 — Vite + React SPA** complete
  - **Tooling**: `apps/web/package.json` (full deps: Vite 6, React 19,
    TS strict, Tailwind v4, TanStack Query+Router, openapi-fetch, lucide,
    shadcn primitives), `tsconfig.json` (strict + `noUncheckedIndexedAccess`
    + `exactOptionalPropertyTypes` + path alias `@/*`), `tsconfig.node.json`,
    `vite.config.ts` (with TanStack Router plugin + Tailwind v4 plugin +
    `/api` proxy to the api container in dev), `eslint.config.js` (flat
    config), `.prettierrc` (with `prettier-plugin-tailwindcss`).
  - **Entry**: `index.html` (replaces the plan-02 placeholder) + `src/main.tsx`
    (QueryClientProvider → RouterProvider → root); React Query Devtools
    in dev only.
  - **Design system**: Tailwind v4 design tokens in `src/styles/index.css`
    under `@theme` — dark canvas, Red Hat-red accent, status palette,
    score-bucket palette, typography + radius scale.
  - **shadcn primitives**: Button (cva variants: default/secondary/ghost/
    outline/danger × default/sm/lg/icon) + Card family. Both styled via
    Tailwind tokens.
  - **Layout**: `Sidebar.tsx` (3-section nav: Discover / Team / Tools with
    lucide icons, active-route highlighting via TanStack Router's
    activeProps) + `TopBar.tsx` (env badge + LLM cost meter + notification
    bell — placeholders wired to real endpoints later).
  - **Routes** (file-based): `__root.tsx` (AppShell wrapper), `/` redirects
    to `/dashboard`, plus placeholder pages for dashboard, conferences,
    conferences/[id], smes, audiences, messaging, agent, graph,
    diagnostics, settings.
  - **Containerfile**: spa-builder stage now actually runs
    `corepack enable && pnpm install && pnpm build`; output flows through
    to `/app/static/` in the runtime image.
  - **Makefile**: `make build-spa` works via a throwaway UBI node-22
    container (uses `CONTAINER_CLI` auto-detected docker/podman).
  - **`.gitignore`**: added `apps/web/src/routeTree.gen.ts` (auto-generated
    by the TanStack Router plugin).
  - `docs/ARCHITECTURE.md` — new "Frontend" subsection with stack table
    and dev/prod workflow.
  - **Runtime validation**: pending Docker/Podman + `pnpm install` against
    the real registry. The TS strict / ESLint / Vite-build verification
    happens once the container builds.
- 🐛 **Bug fix** before plan 09 backend: `apps/api/app/db/models/vectors.py`
  had a `text` column that shadowed `sqlalchemy.text()` used on the next line.
  Aliased the import to `sql_text` to break the shadow. Caught by importing the
  whole codebase in a temp venv against real SQLAlchemy. **The full codebase now
  imports cleanly; ORM registers 30 tables.**
- 🚧 **Plan 09 — Manual data entry, backend pass** complete
  - `apps/api/app/services/_common.py` — `paginate(stmt, page, per_page)` →
    `(rows, total)`; `write_audit(action, target_type, target_id, before, after,
    actor_label)` stages an audit-log row; `model_to_audit_dict(obj)` serializes
    ORM rows to JSONB-friendly dicts.
  - `apps/api/app/services/messaging_service.py`,
    `audience_service.py`, `sme_service.py`, `past_conference_service.py`,
    `topic_service.py` — list / get / create / update / soft-delete per entity.
    SME service also does FK existence checks on `primary_topics` +
    `audience_focus` (denormalized array columns; no DB-level FK constraints).
    Past-conference service has a CSV import path: row-by-row validation
    against `PastConferenceCSVRow`, name→UUID resolution against active SMEs,
    all-or-nothing transaction by default, formula-injection quoting.
  - `apps/api/app/api/v1/messaging.py`, `audiences.py`, `smes.py`,
    `past_conferences.py`, `topics.py` — routers wire the services to FastAPI
    + `DbSession` dependency + Pydantic response models.
  - Topic admin: `POST /api/v1/topics/{id}/approve` (promotes LLM-discovered
    topics from `pending_review=true, is_active=false` to active);
    `POST /api/v1/topics/{id}/reject` (audit-logged deactivate).
  - `apps/api/app/main.py` includes all 5 new routers.
  - `apps/api/app/schemas/common.py` — added `Page[T]` (generic paginated
    response) + `READ_CONFIG` (ConfigDict with `from_attributes=True`).
  - Every `*Read` schema fixed: `created_at`/`updated_at` typed as `datetime`
    (was `str`); inherits `READ_CONFIG` for ORM serialization.
  - `python-multipart` added to deps (needed by `UploadFile` in the CSV import).
  - **Verified**: full codebase imports against real Pydantic + SQLAlchemy +
    asyncpg in a temp venv. **32 routes** registered including 27 from this
    pass. Pydantic Create-schema instantiation + rejection-of-bad-input both
    behave as designed.
- 🚧 **Plan 09 — Manual data entry, UI pass** next (multi-step wizards for
  messaging + audience entry; form pages for SME + past conferences; topic
  review queue; CSV drop-zone). All consume the 27 endpoints landed in this pass.

### 2026-05-21 (afternoon revision)
- 🔄 **Docling adopted** for PDF parsing + structure-aware chunking
  ([ADR-0003](../docs/ADR/0003-docling-for-pdf-and-chunking.md))
  - Plan 11 revised: `HybridChunker` replaces `langchain-text-splitters`
  - Plan 12 revised: Docling `DocumentConverter` replaces `pypdf` + `ocrmypdf`
  - Plan 04 revised: `document_chunks.chunk_metadata jsonb` added — captures
    Docling's structural info (section heading, page number, content type)
    so the agent chat (plan 22) can cite page + section, not just chunk index
  - `docs/data-model.md` + `docs/ARCHITECTURE.md` updated
  - **Drops three deps**, picks up one heavier one (~500MB-1GB image cost
    for layout models). Multi-format upside: DOCX/PPTX/HTML upload paths
    become trivial later.

---

## Open decisions still pending answer

These block specific later plans but not 01–06.

1. **Monthly MaaS budget per install** (plan 10) — recommending $50 default
2. **Scraper source list approval** (plan 14) — proposed list awaits sign-off
3. **Strategic pillars + audience industries text** — to be entered via XLSX workbook (plan 31)
4. **Container registry**: ghcr.io vs Quay (plan 28)
5. **License confirmation** — Apache 2.0 unless overridden (plan 01)
6. **Llama-Guard-3-1B optional safety classifier** — on or off by default (plan 29)
7. **Exact MaaS endpoint URL** for `.env.example` (plan 07)
