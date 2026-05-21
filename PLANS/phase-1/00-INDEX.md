# DAAM Scout — Phase 1 Implementation Index

This is the master tracker for **Scout**: a locally-installed web app that
finds AI conferences, scores them against the team's messaging and the
four-pillar strategy, and recommends which SME should attend.

## Architecture in one paragraph

End users `git clone`, copy `.env.example` to `.env`, fill in their Red Hat
MaaS API key, and run `docker compose up` (or `podman compose up`).
**Two containers** come up: **postgres** (with pgvector) and **api** (FastAPI
with APScheduler in-process; serves both the JSON API and the built React SPA
via `StaticFiles`). The api calls Red Hat MaaS over the OpenAI-compatible
API for both chat and embeddings. No auth (single user, local). No Redis,
no separate worker, no separate web container, no Prometheus/Grafana stack.
The knowledge graph lives as junction tables in Postgres and is computed
in-memory with NetworkX (the Obsidian model). User-input data goes through
strict structured-entry guardrails — no freeform-paste-and-parse.

## Stack lock-ins

- **Framework**: Route 1 — FastAPI + Postgres/pgvector + React SPA + MaaS via OpenAI-compatible API
- **Runtime**: Docker Compose **and** Podman Compose, single `compose.yaml`
- **Containers**: 2 services — `postgres`, `api` (api serves the SPA)
- **Database**: Postgres 16 + pgvector + pg_trgm + unaccent + pgcrypto
- **Background jobs**: APScheduler in the API process, jobstore in Postgres (no Redis)
- **Graph**: Postgres junction tables + NetworkX in memory
- **Embeddings**: `nomic-embed-text-v1-5` via MaaS (only embedding model available on MaaS), 768 dim
- **Chat model**: `granite-3-2-8b-instruct` via MaaS (Red Hat–aligned, 4M context, $0.50/M tokens). Per-purpose overrides via env if a step needs better reasoning.
- **Frontend**: Vite + React 19 + TS strict + Tailwind + shadcn/ui + TanStack Query + TanStack Router
- **Scraping**: Crawl4AI only (no Playwright)
- **PDF**: pypdf + OCR fallback via ocrmypdf
- **Auth**: none (single-user local install)

## How to use these plans

Each numbered file is a self-contained work package, sized like a GitHub issue.
Work them in order — later files assume earlier ones are done.

Each file uses the same shape:
- **Goal** — what this step delivers
- **Prereqs** — which previous steps must be complete
- **Tasks** — checkbox list
- **Acceptance criteria** — Definition of Done
- **Security notes** — what to harden, inline
- **Open questions** — flag back to Ian before implementing
- **Risks**

## Plan ordering

| #  | File | One-liner |
|----|------|-----------|
| 01 | [01-project-bootstrap.md](01-project-bootstrap.md) | Monorepo layout, uv + pnpm, pre-commit, ADRs, Makefile |
| 02 | [02-containerization-foundation.md](02-containerization-foundation.md) | compose.yaml on Docker + Podman, 2-container stack |
| 03 | [03-data-layer-postgres-pgvector.md](03-data-layer-postgres-pgvector.md) | Postgres 16 + pgvector, extensions, healthcheck, backups |
| 04 | [04-database-schema.md](04-database-schema.md) | Tables for conferences, sources, SMEs, audiences, messaging, matches |
| 05 | [05-data-input-guardrails.md](05-data-input-guardrails.md) | **Strict structured-entry rules for user-input data** |
| 06 | [06-backend-fastapi-skeleton.md](06-backend-fastapi-skeleton.md) | FastAPI app, async SQLAlchemy, Alembic, OpenAPI, serves SPA |
| 07 | [07-config-and-secrets.md](07-config-and-secrets.md) | Single `.env`, MaaS key handling, gitleaks |
| 08 | [08-frontend-vite-skeleton.md](08-frontend-vite-skeleton.md) | Vite + React SPA, design system, typed API client, build into api image |
| 09 | [09-manual-data-entry.md](09-manual-data-entry.md) | Guarded CRUD wizards for messaging, audiences, SMEs, past conferences |
| 10 | [10-llm-service-layer.md](10-llm-service-layer.md) | OpenAI-compatible client for MaaS, retries, cost meter, dry-run |
| 11 | [11-embeddings-and-chunking.md](11-embeddings-and-chunking.md) | nomic-embed-text-v1.5, chunker, pgvector HNSW, model versioning |
| 12 | [12-pdf-rag-ingestion.md](12-pdf-rag-ingestion.md) | PDF upload, parse, OCR fallback, strict purpose rules |
| 13 | [13-background-jobs-scheduling.md](13-background-jobs-scheduling.md) | APScheduler in-process, Postgres jobstore |
| 14 | [14-web-scraper.md](14-web-scraper.md) | Crawl4AI, robots.txt, seeded source list (no Playwright) |
| 15 | [15-data-validation-and-routing.md](15-data-validation-and-routing.md) | LLM extraction, confidence routing, quarantine |
| 16 | [16-knowledge-graph.md](16-knowledge-graph.md) | Junction tables + NetworkX + node-link API |
| 17 | [17-fit-matcher-algorithm.md](17-fit-matcher-algorithm.md) | Multi-stage match: messaging → pillars → SME, with exits |
| 18 | [18-sme-matcher.md](18-sme-matcher.md) | SME ranking on topics/audiences/bio/location/past attendance |
| 19 | [19-sme-fit-narrative.md](19-sme-fit-narrative.md) | LLM fit-narrative for top 3 SMEs per conference (cost-bounded) |
| 20 | [20-dashboard-and-review-ui.md](20-dashboard-and-review-ui.md) | Ranked list, detail view, approve/reject, saved views |
| 21 | [21-graph-exploration-view.md](21-graph-exploration-view.md) | Dashboard-level interactive graph (Obsidian-style) |
| 22 | [22-agent-chat-interface.md](22-agent-chat-interface.md) | RAG-backed chat with citations, no agentic loops |
| 23 | [23-conference-series-tracking.md](23-conference-series-tracking.md) | Link year-over-year editions; powers past-attendance signal |
| 24 | [24-cfp-closing-digest.md](24-cfp-closing-digest.md) | Scheduled digest + in-app notifications for CFPs closing soon |
| 25 | [25-data-lifecycle-decay-versioning.md](25-data-lifecycle-decay-versioning.md) | Ebbinghaus decay + content versions + history viewer |
| 26 | [26-observability-and-diagnostics.md](26-observability-and-diagnostics.md) | Structured stdout logs + `/diagnostics` page |
| 27 | [27-testing-strategy.md](27-testing-strategy.md) | Unit / integration / e2e, deterministic LLM mocks, CodeQL |
| 28 | [28-cicd-pipeline.md](28-cicd-pipeline.md) | GitHub Actions: lint, test, build images, CodeQL, releases |
| 29 | [29-security-review-and-hardening.md](29-security-review-and-hardening.md) | Threat model for local install: prompt injection, PDFs, SSRF |
| 30 | [30-documentation-and-runbook.md](30-documentation-and-runbook.md) | README, ARCHITECTURE.md, SOPs, contributor guide |
| 31 | [31-configuration-workbook-import-export.md](31-configuration-workbook-import-export.md) | XLSX workbook upload/download for team collaboration via Google Sheets |
| 32 | [32-multi-sme-team-recommendations.md](32-multi-sme-team-recommendations.md) | Pick complementary pairs/triples of SMEs for big conferences (algorithmic) |
| 33 | [33-conference-brief-export.md](33-conference-brief-export.md) | One-page printable brief for approved conferences (HTML + print-to-PDF) |

## Open decisions remaining

These are flagged back to Ian. Each is also called out in the specific plan file.

1. **Monthly MaaS budget per install**. See [10](10-llm-service-layer.md).
2. **Scraping legality** — confirm starter source list before [14](14-web-scraper.md) ships.
3. **Strategic pillar text + audience industries** — exact wording needed for seed data.
   With plan [31](31-configuration-workbook-import-export.md), these are now entered via
   the shared XLSX workbook, so you can collaborate on the wording in Google Sheets
   before uploading. See [04](04-database-schema.md), [31](31-configuration-workbook-import-export.md).
4. **Container registry** — ghcr.io or Quay? Affects [28](28-cicd-pipeline.md).
5. **License** — Apache 2.0 unless overridden. See [01](01-project-bootstrap.md).
6. **Optional Llama-Guard-3-1B safety layer** — opt-in defense for prompt-injection
   classification. Cheap ($0.10/M). See [29](29-security-review-and-hardening.md).

## Non-goals for Phase 1

- Multi-user / multi-tenant
- Authentication / SSO
- Salesforce / sales data integration
- Email / social signal ingestion
- Anything in the Phase 2 "Dataverse" expansion
- Public-facing API
- Cloud-hosted production deployment
- JS-heavy site scraping (Crawl4AI only; if needed, add Playwright in a future release)
