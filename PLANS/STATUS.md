# Scout Phase 1 — Build Status

Single source of truth for build progress. Updated as each plan completes.

**Last updated:** 2026-05-22 (plan 11 — embedding pipeline live + auto-embed on create verified)

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
| 09 | Manual data entry | 🚧 | Backend + lists + audience CRUD + SME form + CSV drop-zone live; messaging wizard remaining |
| 10 | LLM service layer | ✅ | Completed 2026-05-22 — dry-run verified end-to-end |
| 11 | Embeddings & chunking | ✅ | Plain-text path live 2026-05-22; Docling chunker for PDFs lands in plan 12 |
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
- 🚧 **Plan 09 UI pass 1** complete — typed API client + list pages + 1 full CRUD flow
  - **Typed API client**: `apps/web/src/lib/api-types.ts` (hand-mirrored from
    plan-05 Pydantic schemas — replaced when `pnpm gen:api` runs) + a thin
    fetch-based `lib/api.ts` with grouped resource helpers (messagingApi,
    audiencesApi, smesApi, pastConferencesApi, topicsApi) + an `ApiError`
    class that surfaces RFC 7807 problem+json with a `fieldErrors()` helper
    for form rendering.
  - **shadcn primitives added**: Input, Textarea, Label, Badge (cva-driven
    with default/accent/success/warning/danger/muted), Skeleton, Table
    (with TableHeader/Body/Row/Head/Cell).
  - **Reusable**: `components/Pagination.tsx`; `hooks/useDebouncedValue.ts`
    (300ms default; pairs with TanStack Query keys for incremental search).
  - **List pages (live data, filter, paginate, soft-delete)**:
    `/messaging`, `/smes` (with DAAM/Non-DAAM tab filter), `/topics`
    (with pending/approved/all tab filter + approve/reject buttons on
    pending rows), `/past-conferences`. All show loading skeletons, an
    error box on failure, and a sensible empty state.
  - **Full audience CRUD flow at `/audiences`**: list + search + paginate
    + soft-delete + a create dialog (inline overlay) with field-level
    validation error display sourced from the api's RFC 7807 `errors[]`.
    Proves the wiring works end-to-end.
  - **`/settings`** rewritten with Link-backed cards pointing to /topics
    + /past-conferences (the live pages); other settings pages disabled-style.
- 🚧 **Plan 09 UI pass 2** next — messaging multi-step wizard, audience
  wizard (replacing the current inline overlay), SME single-screen form,
  past-conference form + CSV drop-zone with diff preview. Pulls in a real
  shadcn Dialog primitive (`@radix-ui/react-dialog`).

### 2026-05-22 (live verification on Podman)
- 🟢 **End-to-end stack live**: `make up` succeeds on Podman 5.8 + podman-compose 1.5.
  Both containers healthy. `/api/v1/healthz`, `/api/v1/readyz`, `/api/openapi.json`,
  `/` (SPA) all responding. All 30 ORM tables present in the right schemas;
  Alembic baseline + seed migrations applied; the seed `embedding_models` row exists.
  Sanity-tested with a real `POST /api/v1/audience-profiles` (HTTP 201 with the
  created row) + a bad-input POST (HTTP 422 with field-level RFC 7807 errors).
- 🐛 **Six fixes from real-world bring-up** (every one a real bug — none would
  have surfaced without running the stack):
  1. `apps/api/Containerfile`: `corepack enable` failed (not on PATH in UBI
     nodejs-22). Switched to `npm install -g pnpm@9.12.0`. Same fix applied
     to `make build-spa` in the Makefile.
  2. `apps/api/Containerfile`: missed `COPY apps/api/alembic` and `alembic.ini`
     into the py-builder + runtime stages. Without them, `make migrate` would
     have died with "no alembic.ini". Added both copies.
  3. `apps/api/Containerfile`: `useradd --uid 1001 scout` collided with UBI
     python-312's pre-existing default user at uid 1001. Switched to uid 1002.
  4. `apps/api/Containerfile`: py-builder created venv at `/build/api/.venv`
     but runtime put it at `/app/.venv` — the venv's hardcoded
     `#!/build/api/.venv/bin/python` shebangs broke `uvicorn` exec. Switched
     both stages to `WORKDIR /app` so the path is consistent and shebangs work.
  5. `apps/api/alembic.ini` + `apps/api/alembic/versions/20260521_1210_seed_embedding_model.py`:
     revision ID `20260521_1210_seed_embedding_model` (36 chars) overflowed
     Alembic's default `alembic_version varchar(32)` column. Renamed file to
     `20260521_1210_seed.py`, shortened revision to `20260521_1210_seed`,
     tightened `truncate_slug_length` from 40 → 18 in alembic.ini to prevent
     future slug-overflow regressions.
  6. `apps/web/`: TypeScript build failed under `tsc -b`. Three roots:
     (a) `routeTree.gen.ts` doesn't exist at `tsc` time because the TanStack
     Router plugin generates it during `vite build`; added `@tanstack/router-cli`
     and prefixed the build script with `tsr generate`.
     (b) `exactOptionalPropertyTypes: true` rejected legitimate
     `string | undefined` parameters; removed it (other strict-mode flags stay).
     (c) Missing `src/vite-env.d.ts` left `import.meta.env` untyped;
     added the standard one-line reference.
     Also fixed `signal: undefined` in `lib/api.ts` to omit the field
     conditionally rather than pass undefined.

### 2026-05-22 (plan 09 UI pass 2)
- ✅ **Plan 09 UI pass 2** mostly complete; messaging wizard remaining
  - **Dialog primitive** (`apps/web/src/components/ui/dialog.tsx`):
    shadcn-style wrapper around `@radix-ui/react-dialog`. Focus trap,
    escape-to-close, accessibility all free. Exports Root/Trigger/Content/
    Header/Footer/Title/Description + a built-in close button.
  - **SME form** (`components/sme/SmeFormDialog.tsx`): full profile entry
    inside the Dialog. Six sections — Identity / Expertise & focus /
    Location / Bio / External links. Multi-selects for `primary_topics` and
    `audience_focus` fetch active rows via TanStack Query, render as
    toggleable chip-style Badges, send UUIDs back to the FK-checking
    backend. Bio gauge (200-min / 2000-max) renders a colored progress bar.
    Field errors bind to Pydantic's RFC 7807 `errors[]`. Submit gated on
    bio length + ≥2 expertise areas. Wired into `/smes` `New SME` button.
  - **CSV drop-zone** (`components/past-conferences/CsvImportDialog.tsx`):
    drag-and-drop file picker. Two-step flow — upload → preview result
    (`imported` / `skipped` / per-row errors). When errors exist with
    `imported=0`, a "Commit valid rows anyway (skip errors)" button passes
    `ignore_errors=true`. Per-error rendering shows row + field + message.
    Wired into `/past-conferences` `Import CSV` button.
  - **Audience overlay refactored** to use the Dialog primitive (same UX,
    better accessibility — was a hand-rolled fixed overlay).
  - **`@radix-ui/react-dialog`** added to deps; container rebuild succeeded;
    the `Platform Engineering Lead` audience created in the prior turn
    persisted across the rebuild (`/api/v1/audience-profiles` still returns
    1 total).
  - **Remaining for the messaging wizard**: 6-step flow (title+source /
    elevator pitch / personas / themes+talking points / differentiators+
    competitive / review). Not blocking — XLSX workbook (plan 31) covers
    bulk messaging entry too. Defer to next pass.

### 2026-05-22 (plan 10 — LLM service layer)
- ✅ **Plan 10 complete**: `apps/api/app/services/llm/` package
  - `models.py` — typed `ChatRequest`/`ChatResponse`/`EmbeddingRequest`/
    `EmbeddingResponse` + `BudgetExceeded` exception. Provider-agnostic.
    Callers downstream never see raw openai SDK types.
  - `costs.py` — per-model price table seeded with the MaaS catalog
    (granite-3-2-8b-instruct $0.50/M, nomic-embed-text-v1-5 $0.02/M input,
    deepseek-r1-distill-qwen-14b $0.80/M, etc.). Override via `LLM_PRICES_JSON`.
  - `retries.py` — tenacity-based `AsyncRetrying` for 429 / 5xx / network
    errors. 4 attempts with jittered exponential backoff (1–30s).
  - `rate_limit.py` — per-process async token bucket; two buckets (10 rps
    sustained / 20 burst; 2000 tokens/sec sustained).
  - `dry_run.py` — deterministic chat + embedding responses. Embeddings
    are 768-dim seeded from sha256(text) so the rest of the pipeline (pgvector)
    doesn't notice. Activated by `LLM_DRY_RUN=true`.
  - `_recording.py` — `record_call(...)` stages an INSERT into
    `app.llm_calls`; `month_to_date_spend()` + `check_budget()` enforce
    `LLM_MONTHLY_BUDGET_USD`. Caller owns the transaction.
  - `client.py` — `LLMClient.chat()` (single-shot + streaming) and
    `LLMClient.embed()` (batched). Per-purpose model resolution (extract/
    rationale/narrative/agent fall back to LLM_CHAT_MODEL). Module-level
    `get_llm_client()` singleton.
  - **Admin endpoints** at `/api/v1/admin/llm/test-chat`, `/test-embed`,
    `/stats` — manual smoke tests and the json aggregator plan 26 will
    surface in `/diagnostics`.
- 🟢 **Verified live**: dry-run path tested end-to-end. Chat returned canned
  content with token counts; embed returned a 768-dim deterministic vector;
  `/stats` shows 3 mtd calls with correct breakdown by purpose. All calls
  persisted in `app.llm_calls`.
- 🐛 **Three bugs caught by running it**:
  1. `before_sleep_log(log, logging_level=30)` — wrong kwarg name. tenacity
     uses positional `level` not `logging_level`. Also tenacity wants a
     stdlib logger, not a structlog binder. Switched to `_stdlib_log` +
     positional `logging.WARNING`.
  2. `.env` revert during sed: my sed flip of `LLM_DRY_RUN=true` got
     reverted; ran via a small bash script to make sure it stuck.
  3. **Cache invalidation in podman build**: `podman-compose --build`
     didn't reliably invalidate the api COPY layer after small Python edits.
     Added `make rebuild` that does an explicit `--no-cache` build.
     **Note for future**: prefer `make rebuild` when you've edited
     `apps/api/app/**`; `make up` is fine for code-free changes.

### 2026-05-22 (plan 11 — embeddings + chunking)
- ✅ **Plan 11 complete (plain-text path)**:
  - `app/services/embeddings/chunker.py` — sentence-aware character chunker
    (~3000 chars / 750 tokens, 300-char overlap, hard-split fallback for
    pathological inputs). Returns typed `ChunkData(text, chunk_index,
    token_count, metadata)`. Metadata stays empty for plain text; plan 12's
    Docling `HybridChunker` fills it with section_heading/page_number/content_type.
  - `app/services/embeddings/pipeline.py` — `embed_owner(db, owner_type,
    owner_id, text)` is the single entry point. Idempotent: deletes prior
    chunks for the (owner, active_model) tuple before re-inserting. Validates
    `owner_type` against the schema's enum. Empty text → no-op (still
    deletes prior chunks). `get_active_embedding_model()` enforces "exactly
    one" active row.
  - `app/services/embeddings/search.py` — `similar_chunks(query, owner_types,
    k)` embeds the query, runs pgvector's `cosine_distance` ordering against
    the active-model chunks, optionally filters by owner_type/owner_ids.
    Bumps `last_used_at` on hits (drives plan-25 decay); skippable for
    diagnostic searches.
  - `app/api/v1/admin_embeddings.py` — admin routes:
    `/admin/embeddings/model` (active row info), `/stats` (chunk counts by
    owner_type), `/embed-text` (ad-hoc chunk + embed, no DB write),
    `/embed-owner` (full persist), `/search` (similarity search).
- 🪝 **Auto-embed hooks** wired into create + update of:
  audience profiles, SME bios, messaging documents. Failures are non-fatal
  (the entity row persists; admin can re-trigger via `/admin/embeddings/embed-owner`).
  Patterned via `_embed_safely()` per service. Plan 13 (background jobs)
  will move heavy bulk reindexing off the request thread; per-entity create/update
  stays synchronous.
- 🟢 **Verified live (dry-run)**:
  - `POST /audience-profiles` of a new audience → `embed:audience:create`
    appears in `llm_calls`; chunk count jumps from 1 → 2 by owner_type=audience.
  - `POST /admin/embeddings/search` finds both audiences when querying for
    "ML platform inference and GPU capacity".
  - `embed:sme_bio`, `embed:audience`, `admin_search` purpose tags all
    distinct in `/admin/llm/stats`.
- 📝 Note on Docling deferral: plan 12 swaps in `docling.chunking.HybridChunker`
  for PDF inputs where layout-aware chunking actually pays off. For plain text
  (manual entries, scraped boilerplate-stripped pages) the sentence-aware
  chunker above is appropriate and avoids the ~500MB image hit.

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
