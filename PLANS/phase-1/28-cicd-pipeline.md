# 28 — CI/CD Pipeline

## Goal
Automate lint → test → build → CodeQL on every PR. Build and publish the
**single api image** on main; "deploy" is `git pull && docker compose up`
on the user's own machine.

## Prereqs
- 01 (repo on GitHub recommended for CodeQL)
- 02 (Containerfile works locally)
- 27 (tests exist)

## CI

### `.github/workflows/ci.yaml`

- [ ] **Job: lint**
  - Setup uv + pnpm
  - `make lint` (ruff, mypy, eslint, prettier, hadolint, gitleaks, markdownlint)
- [ ] **Job: typecheck**
  - `make typecheck` (mypy strict on api; `tsc --noEmit` on web)
- [ ] **Job: test-unit**
  - `pytest tests/unit -x`
- [ ] **Job: test-integration**
  - GH Actions `services:` for Postgres
  - `pytest tests/integration`
- [ ] **Job: test-web**
  - `pnpm test` + `pnpm build`
- [ ] **Job: e2e** (gated by `e2e` PR label + always on main)
  - Brings up compose, runs Playwright, uploads screenshots on failure
- [ ] **Job: build-image** (PR + main)
  - `docker buildx` for the single api image (multi-stage: SPA + Python + runtime)
  - SBOM via `syft`
  - **Trivy** scan; fails on `HIGH,CRITICAL`
  - Weekly cron: `podman build` against the same Containerfile to catch drift
  - Tags: `scout/api:<sha>`; on main: `:main`; on PRs: `:pr-<n>`

### `.github/workflows/codeql.yaml`
- [ ] CodeQL Action v3
- [ ] Languages: `python`, `javascript-typescript`
- [ ] Suites: `security-and-quality`, `security-extended`
- [ ] Triggers: push, PR, weekly cron
- [ ] Findings annotate PRs; HIGH-severity blocks merge via branch protection.

### `.github/workflows/release.yaml`
- [ ] Triggered by git tag `v*`
- [ ] Retags `:main` as `:v1.2.3` and `:latest`
- [ ] Generates changelog from Conventional Commits (`release-please` or `git-cliff`)
- [ ] GitHub Release with install snippet + SBOM attached

## Distribution model

Local install only. Users get:
- Tagged image at `ghcr.io/<org>/scout/api:<version>`
- `compose.yaml` referenced by tag
- Install: `git clone && cp .env.example .env && make up`
- Update: `git pull && docker compose pull && make up`

No auto-deploy. If we later add a managed-cluster fallback, add an OpenShift
workflow then.

## Branch protection on main
- [ ] Required checks: lint, typecheck, test-unit, test-integration, test-web,
      build-image, codeql.
- [ ] At least one approving review.
- [ ] Linear history.
- [ ] No force-push to main.

## Security notes
- Trivy gate blocks known-vulnerable deps.
- CodeQL catches injection / taint / dataflow issues.
- Image build pulls only pinned base images; no `:latest`.
- Release workflow uses GH OIDC + GHCR; no long-lived registry creds.
- SBOMs attached to releases for downstream audit.

## Acceptance criteria
- [ ] PR fires the workflow; statuses visible on the PR.
- [ ] Trivy blocks PRs that introduce HIGH/CRITICAL CVEs.
- [ ] CodeQL findings annotate the PR diff.
- [ ] Tagging `v0.1.0` builds versioned image + creates release with changelog + SBOM.
- [ ] Weekly Podman cron build is green.

## Open questions for the user
- **Container registry** — ghcr.io (recommended; easy with GH Actions) vs Quay.
- **Public vs private repo** — affects whether installers need a registry token.

## Risks
- CI minutes can balloon. E2E gated by label.
- Docker buildx ↔ Podman drift; weekly cron catches it.
