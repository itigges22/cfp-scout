# 01 — Project Bootstrap

## Goal
Set up the empty repo so every future step has a place to land. Pin
languages, lay out the monorepo, set up code quality tooling, and define
the contribution loop. No application logic yet.

## Prereqs
None.

## Tasks
- [ ] Create top-level monorepo layout:
  ```
  /apps
    /api          # FastAPI service (also serves the built SPA + APScheduler)
    /web          # Vite + React SPA (build artifacts copied into api image)
    /scraper      # Scraping helpers (Python package imported by api tasks; NOT a separate container)
  /packages
    /shared-types # OpenAPI-generated TS types for the web SPA
  /infra
    /compose      # compose.yaml + podman overrides
    /containerfiles
    /postgres     # init SQL for extensions + seeds
  /db
    /seeds        # seed data CSV/JSON
  /PLANS          # already exists
  /docs
    /ADR          # architecture decision records
    /ops          # runbooks (added in step 30)
  /evals          # LLM evaluation fixtures (step 27)
  /.github
    /workflows
  ```
- [ ] `git init`, default branch `main`. `.gitignore` for Python
      (`__pycache__`, `.venv`, `*.egg-info`), Node (`node_modules`, `dist`),
      OS junk (`.DS_Store`), envs (`.env*` but allow `.env.example`), and
      keys (`*.pem`, `*.key`).
- [ ] Pin tool versions (used by containers and CI, not host):
  - Python 3.12 (`pyproject.toml`)
  - Node 22 LTS (`.nvmrc`)
  - Postgres 16 (`compose.yaml`)
- [ ] **Python package manager: `uv`.** Fast, lockfile-based.
- [ ] **JS package manager: `pnpm`.** Reproducible.
- [ ] Pre-commit hooks at repo root:
  - `ruff` (lint + format) on Python
  - `mypy --strict` on `apps/api`
  - `eslint` + `prettier` on `apps/web`
  - `hadolint` on Containerfiles
  - `gitleaks` for accidental secret commits
  - `markdownlint` on `docs/` and `PLANS/`
- [ ] `LICENSE` — recommend **Apache 2.0** unless overridden.
- [ ] Root `README.md`: one paragraph on Scout, quickstart
      (`cp .env.example .env && make up`), pointer to docs.
- [ ] `docs/ARCHITECTURE.md` skeleton — filled in as we go.
- [ ] `docs/ADR/` with `0000-template.md`. First ADR records Route 1 +
      local-install pivot + 2-container architecture.
- [ ] `Makefile` (or `justfile`) at root. Targets fill in across steps:
  - `make up`, `make down`, `make logs SERVICE=`, `make sh SERVICE=`, `make ps`
  - `make test`, `make lint`, `make migrate`, `make seed`
  - `make build-spa` (builds the web SPA into `apps/api/static`)
  - `make nuke` (down -v with confirmation)
  - **Auto-detects `docker compose` vs `podman compose`**:
    ```make
    COMPOSE := $(shell command -v podman-compose 2>/dev/null \
                       || (command -v podman >/dev/null && echo "podman compose") \
                       || echo "docker compose")
    ```

## Security notes
- gitleaks pre-commit + CI gate prevents accidental MaaS key commits.
- `.env.example` committed; `.env` is not.
- ADR-0001 documents the security posture: single-user local install, no auth,
  threat model centered on prompt injection, malicious uploads, scraper SSRF.

## Acceptance criteria
- [ ] Fresh clone → `make help` prints all targets without error.
- [ ] `pre-commit run --all-files` passes on the empty repo.
- [ ] No committed secrets, no `node_modules`, no `.venv`.
- [ ] ADR-0001 merged, linked from `docs/ARCHITECTURE.md`.

## Open questions for the user
- **License** — Apache 2.0 default.
- **Remote git host** — GitHub recommended for CodeQL integration. Confirm.
- **Monorepo confirmed** — three logical packages share types and compose. Confirm.

## Risks
- Tool sprawl. The toolchain is fixed: uv, pnpm, ruff, mypy, eslint,
  prettier, pre-commit, gitleaks, hadolint, markdownlint. Resist adding more.
