# Scout

**Find AI conferences worth attending. Pick the right teammate to send.**

Scout is a private web app for AI-event discovery. It crawls the public web for AI events, scores each one against your team's messaging and strategy, and recommends which subject-matter expert should submit a talk or attend.

Runs entirely on your laptop. The only outside service is your LLM endpoint for chat and embeddings.

---

## Why use it

If you're on a developer-advocacy or AI-marketing team, you've probably done some version of this manually: subscribing to newsletters, bookmarking CFP pages, debating which events fit which narrative, and trying to remember who spoke where last year.

Scout collapses that into one place. Load your reference data once (SMEs, audiences, messaging), and Scout:

- Pulls thousands of upcoming AI events from public feeds
- Filters with a multilingual keyword list (English, Spanish, Portuguese, French, German, Japanese, Chinese, Korean)
- Scores each event against your messaging, strategic pillars, and SME bench
- Surfaces a ranked list with rationale you can hand to a manager
- Generates a print-ready one-page brief for any event

---

## What you get

**Dashboard** - Roll-up numbers, a world map of AI events, top-ranked event cards, and a chat box for quick lookups.

**Conferences** - Ranked list of every event. Detail pages show overall fit score, recommended SMEs with per-dimension breakdowns, source pages, and approve/reject buttons. "Discover more" pulls fresh events from the feed.

**Conference Brief** - Print-optimized one-pager per event: dates, location, why we're going, who should attend, CFP info, talking points.

**SMEs** - Directory of your team. Bio, topics, audience focus, location, past conferences. The matcher uses all of this for recommendations.

**Audiences** - Personas you're targeting (role, seniority, pain points, key messages). Used by the matcher for audience-overlap scoring.

**Messaging** - Active positioning docs with elevator pitch, themes, talking points, differentiators. The matcher scores events against these.

**Attendance** - Tracked per-conference. Each person gets a row (spoke, booth, attended, sponsored) with cost and headcount. Feeds the ranker for next time.

**Agent chat** - Read-only RAG chat. Ask anything about your data in plain English, get cited answers.

**Diagnostics** - System health, LLM budget, background jobs, data freshness.

**Settings** - All tunables in one place (matcher weights, gate thresholds, AI keyword filter, discovery sources). Updates live without restart.

---

## Install

You'll need Docker Desktop or Podman + podman-compose.

```bash
git clone https://github.com/<your-org>/scout
cd scout
cp .env.example .env       # paste your LLM API key
make up                    # builds images, brings up the stack (~2 min first time)
make migrate               # creates schema + seeds conference series catalog
```

Open <http://localhost:8000>. If you don't have an LLM API key yet, set `LLM_DRY_RUN=true` in `.env` to run with canned responses.

---

## First-time setup

Scout needs your team data before it can recommend anything. Enter it through the UI (each section has a **New** button, rows are clickable to edit).

**Minimum for useful results:**

- At least one messaging document
- At least one SME with a real bio and 2+ topic assignments
- At least one audience

Then click **Discover more** on `/conferences` to start pulling events.

---

## How discovery works

1. Hits a public JSON feed of developer events (5,000+ entries, refreshed daily)
2. Filters with a 148-keyword AI list covering 8 languages
3. Creates rows, generates embeddings, queues for the matcher
4. First view of an event scores it inline (5-30 seconds). After that, instant.
5. Coordinates get geocoded via OpenStreetMap for the world map

A nightly job runs the same pipeline plus a web crawl. See [`docs/web-discovery.md`](docs/web-discovery.md) for details.

---

## Backup and restore

Export all settings (including API keys) via `GET /api/v1/admin/settings/export`. Re-import with `POST /api/v1/admin/settings/import`.

> The export contains API keys unmasked. Save with `chmod 600`, don't commit to git.

Reference data (pillars, SMEs, audiences, topics, series) lives in Postgres and is covered by a database backup.

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - System overview, data flow, glossary
- [`docs/web-discovery.md`](docs/web-discovery.md) - Events feed, AI filter, geocoding
- [`docs/data-model.md`](docs/data-model.md) - Tables and columns
- [`docs/ops/runbook.md`](docs/ops/runbook.md) - Start here when something breaks
- [`docs/ops/`](docs/ops/) - Per-topic runbooks (backups, secrets, migrations)
- [`docs/security/SECURITY_REVIEW.md`](docs/security/SECURITY_REVIEW.md) - Threat model
- [`docs/ADR/`](docs/ADR/) - Architecture decision records

---

## Reporting a security issue

Open a GitHub issue tagged `security`, or email the maintainers directly. Don't include sensitive payloads in public issues.

---

## License

[Apache 2.0](LICENSE)
