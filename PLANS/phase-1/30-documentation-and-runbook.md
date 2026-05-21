# 30 — Documentation & Operational Runbook

## Goal
The handoff package. A new teammate (or future-Ian on a fresh laptop) goes
from `git clone` to working dashboard in 15 minutes following only the README.
Operators troubleshoot common issues without reading source.

## Prereqs
- Everything else in Phase 1 at or near complete.

## What to write

### `README.md` (project root)
- One paragraph: what Scout is, who it's for, screenshot.
- **Quickstart**:
  ```
  git clone https://github.com/<org>/scout
  cd scout
  cp .env.example .env   # add your Red Hat MaaS key
  make up
  ```
  Open `http://localhost:8000`.
- Prereqs: Docker Desktop **or** Podman + podman-compose.
- Pointers to `docs/ARCHITECTURE.md` and `PLANS/phase-1/00-INDEX.md`.
- "Report a security issue" section with contact path.

### `docs/ARCHITECTURE.md`
- Mermaid system diagram.
- **2-service layout**: postgres + api (api serves the SPA, runs APScheduler, calls MaaS).
- Data flow: ingest → validate → match → narrative → review.
- Stack table with versions + one-line "why."
- Glossary: SME, DAAM, pillar, audience, CFP, series.

### `docs/ADR/`
- 0001 — Route 1 + local-install pivot + 2-container architecture
- 0002 — Postgres + pgvector; NetworkX in-memory graph (no AGE/Neo4j)
- 0003 — APScheduler in-process; no Redis, no separate worker
- 0004 — nomic-embed-text-v1.5 as starting embedding model
- 0005 — Vite + React SPA served by FastAPI (no Next.js, no web container)
- 0006 — shadcn/ui over PatternFly
- 0007 — uv + pnpm
- 0008 — `Containerfile` naming + Docker/Podman commitment
- 0009 — No auth (single-user local install)
- 0010 — Crawl4AI only; no Playwright in Phase 1
- 0011 — Strict structured-entry guardrails on user data
- 0012 — LLM fit narrative limited to top-3 SMEs per conference

### `docs/ops/`
- `runbook.md` — common ops:
  - "Postgres volume is full"
  - "API container won't start"
  - "Job stuck for hours"
  - "LLM calls suddenly all failing"
  - "Reset the embedding model"
  - "Rotate the MaaS key"
  - "Restore from backup"
  - "Re-run a failed cfp_digest"
  - "Approve a pending topic / series suggestion"
- `incident.md` — incident response template
- `secrets.md` — `.env` permissions, key rotation procedure, where to provision MaaS keys
- `embedding-model-change.md` — SOP for promoting a new embedding model
- `legal-scraping-checklist.md` — vetting a new source before enabling
- `ocr.md` — when OCR fires, how to debug
- `decay-tuning.md` — how to read the freshness histogram in `/diagnostics`
- `series-management.md` — manual series creation + alias maintenance

### `docs/CONTRIBUTING.md`
- Branch naming: `feat/`, `fix/`, `chore/`, `docs/`
- Conventional Commits (drives changelog)
- PR template (`.github/PULL_REQUEST_TEMPLATE.md`)
- How to run tests; how to bump `algorithm_version`
- Local dev tips (live reload, dry-run mode, Vite dev server)

### `docs/API.md`
- Tiny — mostly: "See `/api/openapi.json`."
- Notes: no auth; local-only by default.

### `docs/UI-GUIDELINES.md`
- Design tokens, spacing scale, when to use which shadcn primitive
- Wizard pattern reference (step 09)
- Accessibility minimums

## Tasks
- [ ] Plain markdown under `/docs` rendered on GitHub. No mkdocs build.
- [ ] CI lints markdown (markdownlint) + dead links.
- [ ] Plan docs in `/PLANS/phase-1/` marked done with completion date.
      Long-lived docs (data model, architecture decisions) moved or cross-linked.
- [ ] Demo seed: `make demo-seed` loads realistic anonymized dataset.
- [ ] Walkthrough video (5 min Loom or asciinema cast) linked from README.

## Security notes
- README explicit: anyone with host access has app access — no auth model.
- `docs/ops/secrets.md` describes safe rotation: edit `.env`, `make down && make up`,
  verify in `/diagnostics`.
- Demo seed data anonymized; no real RH messaging in publicly-shared screenshots.

## Acceptance criteria
- [ ] Cold-clone test: a teammate goes from `git clone` to working dashboard
      in < 15 min using only the README.
- [ ] Every ADR linked from `docs/ARCHITECTURE.md`.
- [ ] Each runbook procedure tested at least once.
- [ ] `markdownlint` + link-check pass in CI.

## Open questions for the user
- **OSS vs internal docs** — anything that needs redaction before OSS release?
- **Demo seed** — real audience profile names with light anonymization, or full synthetic?

## Risks
- Docs rot. Counter with: ADRs as immutable history, runbooks tested quarterly,
  plan docs dated when marked done.
