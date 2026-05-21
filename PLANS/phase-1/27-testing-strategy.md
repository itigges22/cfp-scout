# 27 — Testing Strategy

## Goal
A test pyramid that catches regressions without becoming a tax. Designed
for an LLM-heavy app — the easy mistake is treating the LLM as the unit
under test instead of a dependency.

## Layers

### Unit (fast, deterministic, many)
- Pure functions: chunker, score combiners, validators, dedup logic, decay
  math, graph traversal, narrative post-validation.
- `LLM_DRY_RUN=true` makes the LLM client deterministic.
- pytest + factory_boy for ORM fixtures.
- `apps/api/tests/unit/`.

### Integration (Postgres real, LLM mocked)
- `testcontainers-python` spins up Postgres (works on Docker AND Podman).
- Fresh DB per session; Alembic migrations applied; seed data loaded.
- Transaction-rollback fixture per test.
- `apps/api/tests/integration/`.

### Frontend
- **Vitest** for utility functions, schemas, formatters.
- **Playwright** for routes (smoke + golden path e2e).
- `apps/web/tests/`.

### E2E (real stack)
- `make e2e` brings up compose, seeds data, runs Playwright against
  `http://localhost:8000`.
- Golden path:
  1. Open wizard → create messaging document
  2. Create an audience
  3. Create an SME
  4. Upload a fixture PDF → wait for indexing
  5. Trigger scraper against a local nginx fixture serving sample HTML
  6. See the conference appear → approve
  7. Verify decision in audit log and content_versions
  8. Open chat → ask "why this score?" → response with citations
  9. Open `/graph` → see the network
  10. Trigger cfp digest job → bell badge updates
- `e2e/`.

### LLM evaluation
- `evals/` directory of golden inputs and expected behaviors.
- Run weekly, not every PR.
- Default mocked with recorded fixtures; `@live_llm` marker hits real MaaS
  with a small budget cap.

## Static analysis
- [ ] **ruff** for Python lint + format
- [ ] **mypy --strict** for `apps/api`
- [ ] **eslint** + **prettier** for `apps/web`
- [ ] **TypeScript strict**: `noImplicitAny`, `strictNullChecks`,
      `noUncheckedIndexedAccess`, `noImplicitReturns`, `exactOptionalPropertyTypes`
- [ ] **hadolint** for Containerfiles
- [ ] **markdownlint** for docs + PLANS
- [ ] **gitleaks** for secrets

## CodeQL (GitHub-native)
- [ ] `.github/workflows/codeql.yaml`:
  - Runs on push + PR + weekly schedule
  - Languages: `python`, `javascript-typescript`
  - Query suites: `security-and-quality`, `security-extended`
- [ ] CodeQL gates merges via branch protection (step 28).

## Dependency scanning
- [ ] **Dependabot** for `pip`/`uv` + `pnpm` (weekly)
- [ ] **Trivy** on built images in CI (step 28); fails HIGH/CRITICAL
- [ ] **pip-licenses** + **license-checker** audit (no GPL/AGPL surprises)

## Tasks
- [ ] pytest for `apps/api`. Coverage target: 80% on services + matchers.
- [ ] Vitest for `apps/web`. Coverage target: 70% on utility code.
- [ ] HTML fixtures in `tests/fixtures/html/`.
- [ ] LLM mock fixtures in `tests/fixtures/llm/`.
- [ ] Makefile targets:
  - `make test` (everything except e2e)
  - `make test-unit`, `make test-int`, `make test-web`
  - `make e2e`
  - `make eval` (mocked by default; `LIVE_LLM=1 make eval` for real)
  - `make lint`, `make typecheck`, `make security`
- [ ] CI: unit + integration + frontend + lint + CodeQL on every PR.
      E2E gated by `e2e` label.
- [ ] Each test isolates via transaction rollback. No state leaks.

## Guardrail-specific tests (step 05)
- [ ] Every entity has an e2e test that:
  - empty form → fails
  - minimum-required form → succeeds
  - over-length value → fails with field error
  - unknown field via curl → server 422

## Security notes
- Real MaaS keys only used by `@live_llm`-marked tests. CI uses a dedicated
  low-budget key.
- Test fixtures use synthetic SME data; never real PII.

## Acceptance criteria
- [ ] `make test` < 60s on a dev machine.
- [ ] CI fails on coverage drop > 2 points without an override label.
- [ ] Golden-path e2e passes on a fresh stack.
- [ ] CodeQL workflow runs green; findings annotate PRs.
- [ ] Live-LLM evals produce a weekly report; mocked mode runs offline.

## Open questions for the user
- **Live LLM budget for evals** — suggest $20/month cap.
- **UI snapshot tests** — small set on dashboard layout only; confirm.

## Risks
- LLM nondeterminism poisons tests if unmocked. We mock by default; live
  is opt-in marker.
- Coverage becomes Goodhart-y. Watch for tests that exist only for numbers.
