# Scout — Architecture

> **Status:** skeleton. Filled in as the build proceeds. The authoritative
> design lives in [`PLANS/phase-1/00-INDEX.md`](../PLANS/phase-1/00-INDEX.md).

## One-paragraph summary

Scout is a single-user, locally-installed web app. Two containers come up
via `docker compose up` (or `podman compose up`): **postgres** and **api**.
The api is FastAPI; it serves the JSON API at `/api/v1/*`, the built React
SPA at `/`, and hosts an in-process APScheduler that runs background jobs
(scraping, embedding, matching, decay, CFP digests). The api calls <vendor>
the LLM API over the OpenAI-compatible API for both chat (`llama-scout-17b`)
and embeddings (`nomic-embed-text-v1-5`).

## System diagram

```mermaid
flowchart LR
    subgraph User Machine
        Browser --> API
        subgraph Compose
            API[api<br/>FastAPI + APScheduler<br/>+ built SPA]
            DB[(postgres 16<br/>pgvector + pg_trgm)]
            API --> DB
        end
    end
    API -.OpenAI-compatible HTTPS.-> LLM API[your LLM endpoint]
    API -.Crawl4AI HTTPS.-> Web[(public conference sites,<br/>RSS, sitemaps, ICS, wikicfp)]
```

## Service responsibilities

### `postgres`
- Postgres 16 with `pgvector`, `pg_trgm`, `unaccent`, `pgcrypto`.
- Schemas: `app` (entities + junctions), `vectors` (embeddings), `audit`
  (append-only), `jobs` (APScheduler jobstore). See [ADR-0002](ADR/0002-postgres-schemas-not-databases.md).
- Two roles:
  - `POSTGRES_USER` (from `.env`) — superuser, used by Alembic for migrations only.
  - `app` — runtime role used by the api. SELECT+INSERT+UPDATE+DELETE on
    `app`/`vectors`/`jobs`; **only SELECT+INSERT on `audit`** (defense in depth).
- Backed by named volume `postgres_data`.
- Init SQL: `infra/postgres/init/01-extensions.sql` (extensions) and
  `02-roles-and-schemas.sql` (schemas + role + default privileges).
- Operator runbook: [`docs/ops/database.md`](ops/database.md). Backups: [`docs/ops/backups.md`](ops/backups.md).

### `api`
- FastAPI app (`apps/api/app/main.py`).
- Hosts an `AsyncIOScheduler` started in the FastAPI lifespan.
- Serves the SPA built by `apps/web` as static files at `/`.
- Talks to LLM API via an OpenAI-compatible client. No direct network calls
  to model inference outside of LLM API.

## Data flow

```
Crawl4AI / ICS / wikicfp -> raw_pages -> trafilatura + LLM extract ->
  validate + dedup -> conferences (+ topics + audiences + pillars)
                       -> embeddings (pgvector)
                       -> fit matcher (messaging → pillars → SME)
                       -> SME team rec (1/2/3)
                       -> SME fit narrative (top-3)
                       -> matches row + decisions queue
                       -> dashboard / agent chat / CFP digest / brief export
```

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language (api) | Python 3.12 | Pydantic v2, async SQLAlchemy, FastAPI maturity |
| Language (web) | TypeScript strict + React 19 | Strong typing matches our generated OpenAPI client |
| Build tool (web) | Vite 5 | Lightweight, no SSR needed; built into the api image |
| Router (web) | TanStack Router | Typed routes, file-based |
| State (web) | TanStack Query | Server state; pairs with `openapi-fetch` |
| UI primitives | shadcn/ui + Tailwind v4 | Copy-into-repo, full customization |
| DB | Postgres 16 + pgvector | Single store; HNSW vector search; Apache AGE not needed (NetworkX in-mem) |
| Background jobs | APScheduler in-process | No Redis; jobs persisted in Postgres |
| Graph | NetworkX in-memory + Postgres junctions | Obsidian-style derived graph |
| LLM client | `openai` SDK pointed at LLM API base_url | Provider-agnostic |
| Scraping | Crawl4AI + `icalendar` + dedicated wikicfp parser | No Playwright |
| PDF | pypdf + ocrmypdf fallback | Native then OCR |
| Migrations | Alembic | Standard |

## Glossary

- **team** — <vendor> data and AI advocacy team
- **SME** — subject-matter expert (the your team and external collaborators)
- **CFP** — call for papers; submission window for a conference
- **Pillar** — one of your four strategic pillars
- **Audience** — <vendor>-defined marketing/sales persona
- **Series** — year-over-year linkage between editions of the same conference
- **Match** — the matcher output (scores + recommended SMEs + rationale) for a conference

## Architecture Decision Records

See [`ADR/`](ADR/). The most consequential records:

- [`ADR/0001`](ADR/0001-route-1-local-install-2-containers.md) — Route 1 + local install + 2-container architecture
- [`ADR/0002`](ADR/0002-postgres-schemas-not-databases.md) — Logical separation via Postgres schemas (`app`/`vectors`/`audit`/`jobs`), not multiple databases
- (more added as plans complete)

## Where things are still TBD

These are tracked in [`/PLANS/STATUS.md`](../PLANS/STATUS.md) and the per-plan
"Open questions" sections. As of the current build state, this file will
be updated to reflect concrete choices as they land in code.
