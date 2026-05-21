# Scout Phase 1 — Build Status

Single source of truth for build progress. Updated as each plan completes.

**Last updated:** 2026-05-21 (plan 01 complete)

## Plan status

Legend: ⬜ pending · 🚧 in progress · ✅ complete · ⏸️ blocked

| # | Plan | Status | Notes |
|---|------|--------|-------|
| 01 | Project bootstrap | ✅ | Completed 2026-05-21 |
| 02 | Containerization foundation | ⬜ | |
| 03 | Postgres + pgvector | ⬜ | |
| 04 | Database schema | ⬜ | |
| 05 | Data input guardrails | ⬜ | |
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
- 🚧 **Plan 02 — Containerization foundation** next

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
