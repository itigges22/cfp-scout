# Secrets handling

Scout has one truly sensitive secret — the your LLM endpoint API key — and a
handful of operationally-sensitive values (the Postgres superuser password,
the `app`-role password, future Eventbrite/Meetup API keys if those sources
get enabled). This runbook covers what they are, where they live, how to
rotate them, and what to do if one leaks.

The code that enforces it is in `apps/api/app/settings.py` +
`apps/api/app/logging.py` + `apps/api/app/lifespan.py`.

## What counts as a secret

| Secret | Where | Why it matters |
|--------|-------|----------------|
| `LLM_API_KEY` | `.env` on the user's machine | Authorizes LLM API spend on your team's bill. Stolen → financial impact. |
| `POSTGRES_PASSWORD` | `.env` on the user's machine | Postgres superuser. Anyone with it can drop the database. |
| `APP_DB_PASSWORD` | `.env` on the user's machine | Limited app-role password. Lower impact than the superuser but still grants DB read/write. |
| (future) `EVENTBRITE_API_KEY`, `MEETUP_API_KEY` | `.env` on the user's machine | Per-source scraper keys. Provisioned only when those sources are enabled (plan 14). |

The LLM API key is the one that matters financially. The Postgres passwords
matter only if the database is reachable from outside the compose network —
which it isn't by default.

## Where secrets live (and where they don't)

```mermaid
flowchart TD
    Env[".env<br/>host filesystem, chmod 600"] -->|read by docker compose<br/>or podman compose| ContainerEnv["container env<br/>LLM_API_KEY=..."]
    ContainerEnv -->|pydantic-settings| Settings["Settings.llm_api_key<br/>(SecretStr)"]
    Settings -.->|never written to logs<br/>(structlog redactor active)| Logs[("logs")]
    Settings -.->|never echoed in tracebacks<br/>(ENV=prod strips stack)| Errors[("error responses")]
    Settings -.->|never serialized<br/>to JSON responses| API[("api responses")]
    style Logs stroke-dasharray: 5 5
    style Errors stroke-dasharray: 5 5
    style API stroke-dasharray: 5 5
```

Secrets explicitly do NOT live in:
- The `git` history (`.env` is gitignored; `.env.example` only has placeholders).
- Docker / Podman image layers (no build-time secrets; `pyproject.toml` and
  source code are baked in, the key arrives at runtime via `env_file`).
- `docker run --env LLM_API_KEY=...` style command lines (would show in
  `ps`). Compose's `env_file:` reads `.env` directly into the container's
  environment, not via the shell.
- The compose YAML (`compose.yaml` references `${LLM_API_KEY}` — that's a
  variable expansion at compose-up time, sourced from `.env`).
- Logs. Three layers of defense:
  1. `Settings.llm_api_key` is a `pydantic.SecretStr`. Logging the settings
     object yields `**********`.
  2. `apps/api/app/logging.py` has a redaction processor that scrubs
     `api_key`/`password`/`token`/`secret`/`authorization` keys plus
     bearer/sk-style patterns from string values.
  3. The startup banner in `lifespan.py` calls `settings.model_dump()` —
     SecretStr fields show as `'**********'` in the dump.

## First-time setup (per user, per machine)

```bash
git clone https://github.com/<your-org>/scout
cd cfp-scout
cp .env.example .env
chmod 600 .env                   # restrict to your user only
$EDITOR .env                     # add your LLM key, postgres password
make up
```

Verify the key is being read but not logged:

```bash
make logs SERVICE=api | head -50
```

You should see one line at startup that includes
`"llm_api_key":"**********"` — confirming pydantic-settings parsed the key
but the redactor masked it. If you see the actual key in logs, **stop and
escalate** — the redaction is broken.

## Provisioning a LLM key

1. Open the your LLM endpoint dashboard (URL depends on your environment).
2. Create a new key labeled with your name + `scout` (e.g. `operator-scout`).
   The label makes audit/rotation obvious later.
3. Copy the key into your `.env` as `LLM_API_KEY=...`.
4. `make down && make up` to reload the api with the new value.
5. Hit `/diagnostics` (plan 26, when it lands) or watch `make logs api` to
   confirm LLM API calls work.

## Rotating the LLM key

You should rotate quarterly or any time:
- A teammate with access leaves the project.
- The key is suspected to be compromised (someone else's machine had a copy, etc.).
- LLM API prompts you to.

Procedure:

```bash
# 1. Provision a new key on the LLM provider dashboard (label it with a date)
# 2. Edit the .env to use the new key
$EDITOR .env

# 3. Reload the api container — picks up the new env on restart
make down && make up

# 4. Verify the new key works
make logs SERVICE=api | grep -i 'llm_api_key\|maas'
# (expect '**********' for the key; no errors)

# 5. Revoke the OLD key on the LLM provider dashboard
```

**Do step 5 last.** If you revoke before swapping, in-flight requests fail
and you have to roll back.

## Rotating the Postgres passwords

The superuser (`POSTGRES_USER` / `POSTGRES_PASSWORD`) is set at container
creation. Changing it after the fact requires either:

- **Easy path**: `make nuke && make up` (destroys volume; re-init with new password). Only acceptable if you have a fresh dump first: `make db-dump`.
- **Surgical path**: shell into the running postgres and `ALTER USER scout WITH PASSWORD '...';`, then update `.env` and restart the api.

```bash
# Surgical path
make db-psql
postgres=# ALTER USER scout WITH PASSWORD 'new-strong-password';
postgres=# \q

# Update .env
$EDITOR .env
# POSTGRES_PASSWORD=new-strong-password

# Restart so the api re-reads .env
make down && make up
```

For the limited `app` role — same thing but `ALTER ROLE app WITH PASSWORD ...`
and update `APP_DB_PASSWORD` in `.env`.

## What to do if a secret leaks

Treat these as serious incidents. The first three steps are non-negotiable.

### 1. Revoke immediately
- **LLM key**: log into the LLM provider dashboard, revoke the key, generate a new one.
- **Postgres password**: rotate per "Rotating the Postgres passwords" above.

### 2. Audit what was reachable with the leaked secret
- For LLM API: check the LLM API billing dashboard for unexpected spend in the last 24 hours.
- For Postgres: review `audit_log` for unexpected writes. (Postgres isn't network-exposed by default, so the blast radius is local-machine only — but check anyway.)

### 3. Find how it leaked
- Git history scan: `gitleaks detect --no-git` (or `pre-commit run gitleaks --all-files`).
- Filesystem scan: did `.env` get backed up by a tool that pushes to cloud?
- Logs: did the redactor fail to mask something? Search recent logs for the key prefix (`sk-...` etc.); if found, file an issue and add the pattern to `_REDACT_VALUE_PATTERNS` in `apps/api/app/logging.py`.

### 4. If the secret was committed
If the secret made it into `git` history:

```bash
# Determine which commit
git log -p -S '<the-leaked-prefix>' --all | head -50

# Rewrite history (single-user repo; safe to force-push)
# Use git-filter-repo (preferred over filter-branch):
pip install git-filter-repo
git filter-repo --replace-text <(echo 'leaked-value==>REDACTED')
git push --force-with-lease origin main
```

Then notify any teammates who had cloned the repo — they need to re-clone or
hard-reset their main.

### 5. Post-incident
- Open a security issue on the repo (tag `security`).
- Update this runbook if the failure mode revealed a gap.
- If the key was leaked via a third-party tool (backup, cloud sync), fix the
  tool's scope.

## Defense layers (recap)

In order of "first to fail" → "last line":

1. **`.gitignore`** blocks `.env*` (except `.env.example`).
2. **gitleaks pre-commit hook** scans staged changes for secret patterns before they hit your local repo.
3. **gitleaks in CI** (plan 28; not yet wired) scans on push as a backstop.
4. **SecretStr in settings** prevents accidental `f"{settings.llm_api_key}"` from yielding the raw value.
5. **structlog redactor** scrubs known-sensitive keys + bearer/sk- patterns from log records.
6. **`ENV=prod` strips tracebacks** from error responses so a 500 doesn't leak environment values.
7. **LLM API-side**: per-key billing isolation, revocable independently. A leaked Scout key doesn't compromise other apps that share LLM API access.

## Related

- [`database.md`](database.md) — Postgres role separation, why the api connects as `app` rather than the superuser
- [`backups.md`](backups.md) — `db-dump` artifacts also contain table data; treat backups as sensitive
- [`data-guardrails.md`](data-guardrails.md) — input-side guardrails (different layer of "what we trust")
- [ADR-0001](../ADR/0001-route-1-local-install-2-containers.md) — local-install threat model
- [`docs/security/SECURITY_REVIEW.md`](../security/SECURITY_REVIEW.md) — full security review (Phase 1 close-out)
