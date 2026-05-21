# 07 — Config & Secrets Management

## Goal
A single, boring approach to configuration. For a local install, "secrets"
means the MaaS API key. Protect it, keep it out of git, don't log it.

## Prereqs
- 06 (Pydantic settings in use)

## Principles
- Config in env vars. No config files burned into images.
- `.env` gitignored; `.env.example` committed.
- No values inlined in compose YAML; compose references `${VAR}`.
- Pydantic settings fail loud on missing required keys at startup.
- Same key names everywhere.

## Config surface

Defined in `apps/api/app/settings.py`. Mirrored in `.env.example`.

| Key | Purpose | Required |
|-----|---------|----------|
| `ENV` | `dev` / `prod` | yes |
| `DATABASE_URL` | Postgres DSN | yes |
| `LLM_BASE_URL` | MaaS OpenAI-compatible endpoint | yes |
| `LLM_API_KEY` | MaaS key | yes |
| `LLM_CHAT_MODEL` | `granite-3-2-8b-instruct` (default) | yes |
| `LLM_EMBEDDING_MODEL` | `nomic-embed-text-v1-5` (only embed option on MaaS) | yes |
| `LLM_EXTRACTION_MODEL` | Optional override for step 15 extraction; defaults to `LLM_CHAT_MODEL`. Set to `deepseek-r1-distill-qwen-14b` if reasoning quality demands it. | no |
| `LLM_NARRATIVE_MODEL` | Optional override for step 19 SME narratives; defaults to `LLM_CHAT_MODEL`. | no |
| `LLM_AGENT_MODEL` | Optional override for step 22 agent chat; defaults to `LLM_CHAT_MODEL`. | no |
| `LLM_DRY_RUN` | `true` returns canned responses | no (false) |
| `LLM_MONTHLY_BUDGET_USD` | Cost ceiling/month | no |
| `SAFETY_CLASSIFIER_ENABLED` | Route scraped/uploaded content through Llama-Guard-3-1B before main LLM | no (false) |
| `SAFETY_CLASSIFIER_MODEL` | `Llama-Guard-3-1B` when safety classifier enabled | no |
| `STORAGE_PATH` | Volume path for uploaded PDFs and raw HTML | yes |
| `LOG_LEVEL` | `INFO` / `DEBUG` | no (INFO) |
| `LOG_FORMAT` | `json` / `console` | no (json) |
| `SCHEDULER_TIMEZONE` | APScheduler TZ | no (UTC) |
| `SCRAPER_USER_AGENT` | Identifying UA | yes |
| `SCRAPER_DEFAULT_POLITENESS_SECONDS` | Default delay | no (3) |
| **Matcher tuning (env-only; no UI)** | | |
| `MATCH_M_GATE` | Messaging gate threshold | no (0.55) |
| `MATCH_P_GATE` | Pillar gate threshold | no (0.55) |
| `MATCH_S_GATE` | SME gate threshold | no (0.5) |
| `MATCH_W_MESSAGING` | Weight on messaging | no (0.35) |
| `MATCH_W_PILLAR` | Weight on pillars | no (0.35) |
| `MATCH_W_SME` | Weight on SMEs | no (0.30) |
| `DECAY_ENABLED` | Toggle freshness decay | no (true) |

## Tasks
- [ ] `apps/api/app/settings.py` implements the table as a `BaseSettings`.
- [ ] `.env.example` at repo root with every key, documented, dummy values.
- [ ] `.gitignore` covers `.env*` (allow `.env.example`).
- [ ] gitleaks pre-commit + CI gate.
- [ ] Startup banner: redacted snapshot of all config at INFO. Secrets show `***`.
- [ ] structlog redaction processor scrubs `api_key`, `password`, `token`,
      `secret`, `authorization` patterns from log records; unit-tested.
- [ ] `.env.example` uses placeholders like `LLM_API_KEY=changeme`. A
      validator refuses to start with the placeholder value.

## Security notes
- MaaS API key lives in `.env` (recommend `chmod 600`). Loaded into the api
  via `env_file`. Never passed via Docker `--env` (would show in `ps`).
- Logs never include the key. Redaction tested.
- Startup banner explicitly redacts `LLM_API_KEY` and the password
  component of `DATABASE_URL`.

## Acceptance criteria
- [ ] Removing `LLM_API_KEY` from `.env` and running `make up` fails fast
      with a clear error from the api, not 500s later.
- [ ] `gitleaks detect --no-git` is clean.
- [ ] `.env.example` enumerates every key the app reads.
- [ ] A log line containing the actual API key is impossible (test asserts redaction).

## Open questions for the user
- **Per-user MaaS keys** — each install uses its own key. Confirm.
- **Budget enforcement** — recommend warn-at-80%, hard-stop-at-100%. Confirm.

## Risks
- Config drift across teammates' installs. Single `.env` at repo root is
  the source of truth. README explains where to get a MaaS key.
