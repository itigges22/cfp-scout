# Scout Phase 1 — Security Review (Plan 29)

Single deliberate pass before Phase 1 launch. Most controls were enforced
in earlier plans; this is the consolidated record of where each one lives
and what remains open.

## Threat model

Scout is a **single-user, locally-installed** app. The Postgres + api
containers are only reachable on the compose network; the api binds to
`127.0.0.1:8000` on the host. No public exposure.

**Assets**: LLM API key (financial); messaging documents (internal
positioning); SME profiles (limited PII); decision history (auditable).

**Adversaries that apply**:
- Prompt injection from scraped pages + uploaded PDFs *(biggest)*
- Malicious PDFs (zip bombs, malformed)
- Scraper SSRF (source serving redirect to private IPs)
- Supply chain (dep takeover)
- Insider browse (anyone with shell access reads `.env`)

**Adversaries that don't apply**: external unauthenticated attackers,
cross-tenant, account takeover.

---

## Checklist — what's implemented and where

### Data input guardrails (plan 5)
| Control | Status | Where |
|---|---|---|
| Pydantic `extra='forbid'` on every entity | ✅ | `apps/api/app/schemas/common.py` (`StrictBase`) |
| Strict enums + length caps + format validators | ✅ | `apps/api/app/schemas/{audience,messaging,sme,...}.py` |
| No paste-and-parse paths | ✅ | All create routes use Pydantic schemas |
| CSV import sanitizes formula-injection | ✅ | `apps/api/app/services/past_conference_service.py` (quotes cell-leading `=/+/-/@`) |

### Secrets (plan 7)
| Control | Status | Where |
|---|---|---|
| `.env` gitignored | ✅ | `.gitignore` |
| `.env.example` committed | ✅ | repo root |
| gitleaks pre-commit hook | ✅ | `.pre-commit-config.yaml` |
| No secrets in image layers | ✅ | Containerfile takes envs at runtime; `.env` not COPY'd |
| Structlog redactor scrubs `api_key`/`password`/`token`/`secret`/`authorization` | ✅ | `apps/api/app/logging.py` |
| Startup banner redacts SecretStr surfaces | ✅ | `apps/api/app/lifespan.py` (uses Pydantic `model_dump(mode="json")`) |
| README documents `chmod 600 .env` | ✅ | `docs/ops/secrets.md` |

### Inputs (plans 6, 9, 12, 15)
| Control | Status | Where |
|---|---|---|
| FastAPI inputs validated by Pydantic with `extra='forbid'` | ✅ | All routers + schemas |
| No raw-string SQL | ✅ | All queries via SQLAlchemy ORM / `select()`; the one inline cron query (`scrape_source`) uses parameterized `sql_text(... :stripped)` |
| CSV import quotes formula-injection patterns | ✅ | `past_conference_service.py` |
| File uploads MIME-sniffed, size + page capped | 🚧 | `apps/api/app/services/pdf/storage.py` (25MB + `%PDF-` magic; page cap is plan 29 pass 2) |
| Optional ClamAV sidecar | ⏸ | Deferred — Phase 2 |

### Web (plans 6, 8, 20, 29)
| Control | Status | Where |
|---|---|---|
| CSP, HSTS, X-Frame-Options, Referrer-Policy, X-Content-Type-Options, Permissions-Policy | ✅ | `apps/api/app/middleware/security_headers.py` (plan 29) |
| Same-origin SPA + API → CORS irrelevant in prod | ✅ | api serves SPA from `/static` |
| HTML in user text fields React-escaped on render | ✅ | All TSX uses string-children; no `dangerouslySetInnerHTML` |
| Markdown in chat sanitized | 🚧 | Currently plain-text rendering (no markdown). Pass 2 will wire `rehype-sanitize` when we enable Markdown rendering |

### LLM (plans 10, 15, 17, 19, 22)
| Control | Status | Where |
|---|---|---|
| System prompts delimit retrieved content as untrusted (`<page_text>`, `<retrieved_context>`, `<sme_bio>`, `<evidence>`) | ✅ | `prompts.py` in `extraction/`, `agent/`, `matcher/rationale.py`, `matcher/sme_narrative.py` |
| Structured-output schemas validated before any DB write | ✅ | Pydantic `ExtractedConference`, `NarrativeReply`, etc. |
| Rationale + narrative post-validated against input evidence | ✅ | `matcher/sme_narrative.py::_post_validate` (quote-guard) |
| No tool/function calling in Phase 1 | ✅ | LLM client only does chat + embed |
| Token truncation policy | ✅ | `extraction/cleaning.py` (24KB cap), `sme_narrative.py` (1000-char bio cap) |
| Monthly budget enforced; warn at 80% | ✅ | `llm/_recording.py::check_budget`, `/diagnostics` budget bar with `threshold_warn` |
| Llama-Guard-3-1B classifier | ⏸ | Off by default. Env-gated; document opportunistic enablement |

### Scraper (plan 14)
| Control | Status | Where |
|---|---|---|
| robots.txt honored; per-host daily cache | ✅ | `scraper/politeness.py::RobotsCache` |
| Identifying User-Agent | ✅ | `settings.scraper_user_agent` |
| Per-host token-bucket politeness | ✅ | `scraper/politeness.py::RateLimiter` |
| No CAPTCHA evasion, no auth walls | ✅ | by design — httpx-only, no Playwright |
| **SSRF guard**: blocks RFC1918, 127/8, 169.254/16, link-local v6 | ✅ | `scraper/client.py::_SSRFGuardedTransport`; verified rejecting `127.0.0.1` + `169.254.169.254` |
| Saved HTML named by content sha256 | ✅ | `scraper/storage.py` |
| No Playwright | ✅ | by design |

### Container hardening (plan 2)
| Control | Status | Where |
|---|---|---|
| All services non-root | ✅ | api runs as uid 1002 (`Containerfile`); postgres uses its built-in postgres user |
| All Linux capabilities dropped | 🚧 | compose default; pass 2 will add explicit `cap_drop: [ALL]` |
| Read-only root filesystem | 🚧 | pass 2 (tmpfs for `/tmp` etc.) |
| CPU + memory limits on every service | ✅ | `compose.yaml` |
| No `:latest` tags | ✅ | All images pinned (UBI 9 + pgvector/pgvector:pg16) |
| Postgres bound to compose network only | ✅ | no `ports:` on postgres in `compose.yaml`; dev override only opens to 127.0.0.1 |

### Dependencies (plan 28)
| Control | Status | Where |
|---|---|---|
| Dependabot enabled | ✅ | `.github/dependabot.yaml` |
| Trivy gate on builds | ⏸ | Pass 2 — once we add the image-build CI job |
| CodeQL on push + PR + weekly | ✅ | `.github/workflows/codeql.yaml` |
| Pinned lockfiles | ✅ | `apps/web/pnpm-lock.yaml`; `apps/api/uv.lock` is plan-27-pass-2 |
| License audit | ⏸ | Pass 2 |

### Data (plans 3, 4, 25)
| Control | Status | Where |
|---|---|---|
| Backups via `make db-dump`; restore tested | ✅ | `Makefile`, `docs/ops/backups.md` |
| `audit_log` + `content_versions` append-only at role level | ✅ | `02-roles-and-schemas.sql` (app role only has INSERT+SELECT on audit) |
| `app` role is not the Postgres superuser | ✅ | runtime uses `app`; superuser is `scout` (POSTGRES_USER) only via Alembic |
| PII redaction in logs | ✅ | structlog redactor scrubs secret-shaped patterns; SME profiles never logged in full |

### Operational (plan 30)
- `docs/security/SECURITY_REVIEW.md` ← (this doc)
- Incident + runbook docs land in plan 30

---

## Open items (tracked)

- **PDF page cap**: 25MB byte cap is enforced but no explicit page count.
  Plan 29 pass 2.
- **Markdown sanitizer** for agent chat: not needed today (plain-text
  rendering); wire `rehype-sanitize` if/when we enable Markdown.
- **Container `cap_drop: [ALL]`** + read-only root filesystem: plan 29
  pass 2.
- **Trivy image scan + license audit**: plan 28 pass 2 (with the image
  build CI job).
- **Llama-Guard-3-1B** classifier: optional defense-in-depth; recommend
  off for Phase 1, enable if hostile content slips through.

## Verification probes (run before launch)

Quick manual smoke against a running stack:

```bash
# 1. SSRF guard rejects internal IPs (plan 14)
curl -X POST localhost:8000/api/v1/sources -d '{"name":"loopback","url":"http://127.0.0.1:5432","kind":"page"}'
curl -X POST localhost:8000/api/v1/sources/<id>/crawl-now
# ingest_jobs.error_text should contain SSRFProtectionError

# 2. Security headers present
curl -sI localhost:8000/ | grep -iE 'content-security|x-frame|strict-transport'

# 3. Pydantic extra='forbid' rejects unknown fields
curl -X POST localhost:8000/api/v1/audience-profiles -d '{"name":"x","extra_field":"y"}'  # → 422

# 4. Prompt-injection: a fixture HTML with "ignore previous instructions"
#    should still produce a schema-valid extraction
# (manual; upload via /admin/extraction/parse-now/{raw_page_id})

# 5. Budget gate
# When LLM_MONTHLY_BUDGET_USD * 0.8 < mtd cost, /diagnostics threshold_warn=true
```

## Quarterly review

Re-walk this checklist quarterly. Open items move to `🚧` → `✅` as plan-29
pass 2 lands; new findings get added as rows under the appropriate section
with a Plan 29 pass-3+ tag.
