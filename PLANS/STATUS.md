# Scout Phase 1 — Build Status

Single source of truth for build progress. Updated as each plan completes.

**Last updated:** 2026-05-21 (plan 05 complete)

## Plan status

Legend: ⬜ pending · 🚧 in progress · ✅ complete · ⏸️ blocked

| # | Plan | Status | Notes |
|---|------|--------|-------|
| 01 | Project bootstrap | ✅ | Completed 2026-05-21 |
| 02 | Containerization foundation | ✅ | Completed 2026-05-21. End-to-end `make up` not verified — neither Docker nor Podman installed on this build host. |
| 03 | Postgres + pgvector | ✅ | Completed 2026-05-21 |
| 04 | Database schema | ✅ | Design complete 2026-05-21; ORM + migrations land in plan 06 |
| 05 | Data input guardrails | ✅ | Completed 2026-05-21 |
| 06 | FastAPI skeleton | ⬜ | |
| 07 | Config & secrets | ⬜ | |
| 08 | Vite frontend skeleton | ⬜ | |
| 09 | Manual data entry | ⬜ | |
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
