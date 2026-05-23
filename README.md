# Scout

**Find AI conferences worth attending. Pick the right teammate to send.**

Scout is a private web app for the your team. It crawls the public web for AI events, scores each one against your team's messaging and four-pillar strategy, and tells you which of your subject-matter experts is the best fit to submit a talk or attend.

It runs entirely on your laptop. The only outside service Scout talks to is your LLM endpoint for chat and embeddings — everything else (database, scoring, UI, scraping) is local.

---

## Why use it

If you're on the your team, you've probably done some version of this manually:

- Subscribed to ten newsletters that surface AI conferences.
- Bookmarked CFP pages and forgotten which deadlines are coming up.
- Argued in Slack about whether *this* event fits *that* product narrative.
- Tried to remember which SME has spoken at this conference series before.

Scout collapses that into one place. You load in your reference data once (who your SMEs are, what each one knows, what audiences you target, what your products are saying this quarter), and Scout does the rest:

- Pulls thousands of upcoming AI events from public feeds.
- Filters them with a multilingual keyword list (so you don't miss events in LATAM, Asia, or Europe).
- Scores each one against your messaging, your strategic pillars, and your SME bench.
- Surfaces a ranked list with rationale you can hand to a manager.
- Generates a print-ready one-page brief for any event so the SME going can walk into the venue prepared.

---

## What you get

### The Dashboard
A single page that shows you what to act on this week. Three roll-up numbers (events your team has approved in the next 90 days, events pending your review, CFPs closing in the next 30 days), a dark world map with a red dot on every city hosting an AI event Scout found, your top-ranked events as easy-to-scan cards, and a chat box for asking quick questions like *"what AI events in Europe close their CFP this month?"*

### Conferences
A ranked list of every event Scout has found. Click a row to open the detail page, which auto-scores the event the first time you view it (no command to run) and shows you:

- The overall fit score, broken into messaging / pillar / SME components.
- Which SMEs the matcher recommends, with a per-dimension breakdown (topic overlap, audience fit, bio similarity, location, past attendance).
- The original source pages Scout pulled this from.
- One-click approve / reject so the dashboard's stats stay current.

There's a **Discover more** button at the top that triggers a fresh pull from the events feed — typically surfaces dozens of new candidates per click.

### Conference Brief
A clean, print-optimized one-pager for any event. Header, dates, location, why we're going, who should attend, CFP info, past engagement, talking points to crib from. Built for the SME walking into the venue — open it, print to PDF, and they have everything they need on one sheet.

### Subject-Matter Experts (SMEs)
The directory of who's on your bench. Each SME has a bio, topic coverage, audience focus, location, and a list of conferences they've spoken at before. Click any row to edit. The matcher uses all of this to recommend who should attend each new event.

### Audiences
The personas you're trying to reach (Platform Engineering Lead, ML Platform Lead, C-Suite, etc.). Each one has industry, role seniority, pain points, key messages, and exclusion criteria. The matcher uses these to predict which events will put you in front of the right people.

### Messaging
Active product messaging documents — one per positioning artifact. Each one has an elevator pitch, target personas, key themes, talking points, differentiators, and competitive position. The matcher compares every event's description against these to compute a messaging-fit score.

### Past Conferences
A log of events your team has been to before, who attended, what role they played, and any notes. Drives both the SME ranker (location + past-attendance signals) and the conference-series detector (so if you've been to PyCon US 2024, Scout knows PyCon US 2027 isn't a new conference, it's the next edition).

### Knowledge Graph
A force-directed visualization of how everything connects: conferences ↔ topics ↔ SMEs ↔ audiences ↔ pillars. Useful for spotting clusters ("we have five upcoming events about AI safety but only one SME who covers it") and for answering "why did the matcher recommend this person for that event?". Three sliders let you adjust the layout density to taste.

### Ask Scout (agent chat)
A read-only RAG chat. Ask it anything in plain English about your conferences, SMEs, or messaging documents — it answers with citations to specific rows so you can verify. Examples: *"Which approved events does Sarah have a high fit score for?"*, *"Show me events about MLOps in Europe in Q3"*, *"Which SMEs haven't been assigned to anything in the next 90 days?"*

### Diagnostics
What's the health of the system? Where is the LLM budget going? Which background jobs ran, succeeded, failed? How fresh is each data source? One page with all of it.

### Settings
Everything tunable in one place. The runtime knobs (matcher weights, gate thresholds, AI keyword filter, discovery sources) live under **Settings → Tunables** and update live without a restart. The system uses a JSON file backup of every setting (including your LLM API keys) so you can move installs or recover from a wipe.

---

## Install

You'll need either Docker Desktop, or Podman + podman-compose. That's it.

```bash
git clone https://github.com/<your-org>/scout
cd cfp-scout
cp .env.example .env       # paste your your LLM endpoint API key when you open this
make up                    # builds the images and brings up the stack (~2 min first time)
make migrate               # creates the database schema + seeds the conference series catalog
```

Open <http://localhost:8000> in your browser. That's it.

If you don't have a LLM key yet, leave `LLM_DRY_RUN=true` in `.env` and Scout will run with canned LLM responses so you can poke around the UI offline.

---

## First-time setup: load your data

Scout needs to know about your team before it can recommend anything. Two ways to load:

**Option A — Bulk import (recommended for first-time setup).** Download the XLSX template from **Settings → Workbook** in the running app. It has six sheets: Pillars, Industries, Audiences, SMEs, Topics, Series. Fill them in, upload back. Round-trip-safe, so you can export your current state at any time and re-import after a tweak.

**Option B — One-by-one in the UI.** Each section (`/smes`, `/audiences`, `/messaging`, `/past-conferences`, `/topics`) has a **New** button and clickable rows for edit. Good for adding a single SME or correcting a typo; tedious for bulk seeding.

**The minimum to get useful results:**

- At least one messaging document (so the matcher has something to score events against).
- At least one SME with a real bio and 2+ topic assignments (so the matcher can recommend someone).
- At least one audience (so the matcher can compute audience overlap).

Once those are in, click **Discover more** on `/conferences` and Scout will start pulling events.

---

## Backup and restore (including API keys)

Scout has two separate backup paths because reference data and secrets need different handling:

**Reference data — the XLSX workbook.** Settings → Workbook → Export. Gives you a 6-sheet spreadsheet you can edit by hand, share with a teammate, or commit to a private repo. Contains your pillars, industries, audiences, SMEs, topics, and series catalog. **Does not contain secrets.**

**Settings backup — JSON file with everything (including secrets).** Hit `GET /api/v1/admin/settings/export` to download a JSON file with every runtime setting in it: the 33-key tunables surface (matcher weights, gate thresholds, AI keyword filter, discovery sources) **and** your LLM API keys in plain text. Re-import with `POST /api/v1/admin/settings/import`. This is the "move my install to a new machine" file.

> The settings export contains your API keys unmasked. Save with `chmod 600`, don't commit to git, don't share in Slack. The export endpoint logs a warning every time it runs.

The XLSX workbook + the settings JSON together are a complete backup. Save both before any destructive change.

---

## How discovery works (in plain English)

You click **Discover more** on `/conferences`. Here's what happens:

1. Scout hits a public JSON feed of developer events (5,000+ entries, refreshed daily by a community maintainer).
2. It filters that feed with a 148-keyword AI list that includes English, Spanish, Portuguese, French, German, Japanese, Chinese, and Korean variants — so a Spanish "Inteligencia Artificial" conference and a Japanese "人工知能" event both make it through. You can edit this list from Settings → Tunables.
3. For each event that passes the filter, Scout creates a row, generates embeddings of its description, and queues it for the matcher.
4. The first time you open one of these in the UI, Scout scores it inline (5–30 seconds, with a loading skeleton). After that, it's instant.
5. Coordinates get geocoded in the background using OpenStreetMap so the world map populates.

The nightly scheduled job runs the same pipeline plus a web crawl for anything not in the feed.

For the full pipeline narrative — sources, filter rules, failure modes — see [`docs/web-discovery.md`](docs/web-discovery.md).

---

## Daily use

Most days, you open `/dashboard`. The three roll-up cards tell you what needs your attention. The map shows you where things are. The top picks tell you what to do next. If something looks interesting, you click into it, read the rationale, click **Open brief**, and forward the PDF to the SME.

Once a week, click **Discover more** on `/conferences` to pick up anything new. The pending-review queue on the dashboard tells you what needs a thumbs-up or thumbs-down.

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system overview, data flow diagram, glossary
- [`docs/web-discovery.md`](docs/web-discovery.md) — how the events feed, AI filter, and geocoding fit together
- [`docs/data-model.md`](docs/data-model.md) — every table and column, with the *why* behind each design choice
- [`docs/ops/runbook.md`](docs/ops/runbook.md) — start here when something breaks
- [`docs/ops/`](docs/ops/) — per-topic runbooks (backups, secrets, migrations, database, data guardrails)
- [`docs/security/SECURITY_REVIEW.md`](docs/security/SECURITY_REVIEW.md) — threat model and per-control status
- [`docs/ADR/`](docs/ADR/) — architecture decision records (what we chose and why)

---

## Reporting a security issue

Open a GitHub issue tagged `security`, or email the your team lead directly. Don't include sensitive payloads in public issues.

---

## License

[Apache 2.0](LICENSE)
