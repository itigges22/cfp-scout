# 14 — Web Scraper (Crawl4AI Only)

## Goal
Discover conference web pages, fetch them politely, persist raw results
for downstream cleaning. **Two-phase: raw pages first, ingest second.**
The scraper is a Python package imported by tasks in step 13. **No Playwright** —
Crawl4AI only. If a target site needs JS, we mark the source for manual
follow-up rather than dragging in a 1.5 GB headless browser.

## Prereqs
- 13 (jobs)
- 04 (`sources`, `raw_pages`)

## Architecture

```
scheduler tick (every 15 min)
  -> for each source where due:
     enqueue scrape_source(source_id)
        -> fetch URL list (rss/sitemap/page/api)
        -> for each URL not seen recently:
           crawl4ai fetch + dedup-by-hash
           store raw HTML to volume
           insert raw_pages row
           enqueue parse_raw_page(raw_page_id)  # step 15
  -> update sources.last_crawled_at
```

## Tasks

### Source management
- [ ] Seed `sources` table (see "Starter source list" below).
- [ ] Source kinds:
  - `rss` — RSS/Atom feed
  - `sitemap` — sitemap.xml traversal
  - `page` — fetch a page, find links matching regex
  - `api` — read JSON API (Eventbrite, Meetup; needs API key)
  - `ics` — calendar feed. Parse with `icalendar`; each VEVENT becomes a
    candidate conference. **Structured by definition**: dates, location,
    URL, summary — extracted deterministically with no LLM. Highest-quality
    source kind; use when a conference / aggregator publishes one.
  - `wikicfp` — wikicfp.com is a structured CFP aggregator with a
    machine-readable feed (RSS + scrapable structured pages). Per-source
    config: `wikicfp_query` (e.g. `"AI"`, `"NLP"`, `"machine learning"`).
    Parser is dedicated (not generic HTML extraction) and produces fully
    structured records: name, dates, location, URL, abstract deadline,
    submission deadline, topics. Highest-leverage discovery source for new
    academic conferences.
- [ ] Per-source: `crawl_cadence`, `enabled`, `politeness_delay_seconds`,
      `last_crawled_at`, `robots_allowed`, optional `api_key_env_name`.

### Politeness & legality (REQUIRED before this ships)
- [ ] Honor `robots.txt`. `urllib.robotparser`; cache parsed per-day.
- [ ] User-Agent identifies us: `Scout/1.0 (DAAM Conference Discovery; +https://github.com/<org>/scout)`.
- [ ] Rate limit: 1 request per source per `politeness_delay_seconds` (default 3s). Per-host bucket.
- [ ] Honor `Crawl-delay`.
- [ ] No login walls, no paywalled content, no CAPTCHA evasion.
- [ ] Max pages per crawl per source (default 100).

### Fetching
- [ ] Crawl4AI for HTML extraction.
- [ ] If Crawl4AI returns < 500 chars of meaningful text → source likely
      JS-heavy. Mark the page row `parse_status='needs_js_render'`; do NOT
      block ingestion of other pages. Surface count in `/diagnostics`.
      The user can disable the source or flag it for future Playwright work.
- [ ] Conditional GET via ETag / Last-Modified.
- [ ] Content-hash dedup; same hash → bump `last_seen_at`, skip.
- [ ] Raw HTML → `STORAGE_PATH/raw_pages/<source_id>/<sha256>.html`. DB row stores only metadata + path.

### Output
- [ ] Enqueue `parse_raw_page(raw_page_id)` for each new fetch (step 15).
- [ ] Update `sources.last_crawled_at`.
- [ ] `ingest_jobs.stats` records `pages_fetched`, `pages_skipped`, `errors`, `js_blocked`.

### UI
- [ ] `/settings/sources`: list, add/edit/disable, "Crawl now" button.

## Starter source list (proposed — needs your sign-off)

Static-friendly (Crawl4AI handles well):

Academic / Research:
- ACL / EMNLP / NAACL — `aclweb.org/portal/content/`
- NeurIPS — `nips.cc` (sitemap)
- ICML — `icml.cc`
- ICLR — `iclr.cc`
- CVPR / ICCV / ECCV
- KDD — `kdd.org`
- AAAI — `aaai.org`

Linux Foundation / vendor:
- Open Source Summit — `events.linuxfoundation.org`
- KubeCon + CloudNativeCon — `events.linuxfoundation.org`
- LF AI/Data events — `lfaidata.foundation/events`
- AI Engineer World's Fair — `ai.engineer`
- MLOps World — `mlopsworld.com`
- Hugging Face events — `huggingface.co/events`

Red Hat–internal-aligned:
- Red Hat Summit — `redhat.com/summit`
- AnsibleFest — `redhat.com/summit/ansiblefest`

Aggregators (low cost, good signal):
- Papers With Code events — `paperswithcode.com/events`
- ai-conference-list GitHub markdown indexes (fetch via GitHub API)

**Structured-feed sources (highest quality, recommended-enabled):**
- **wikicfp.com** queries: `AI`, `machine learning`, `NLP`, `computer vision`,
  `MLOps`, `LLM`. Each becomes a `wikicfp` source row. wikicfp returns
  deadlines + topics-of-interest already structured; no LLM extraction needed
  for those fields.
- **ICS feeds** from any conference or aggregator that publishes them. Seed
  the table with known ICS URLs (e.g. some IEEE conferences expose ICS).

APIs (require keys; default disabled):
- Eventbrite API — `/v3/events/search/?q=AI+conference`
- Meetup GraphQL API

**Defaults**: enable academic + Linux Foundation + Red Hat + structured-feed
sources at first boot. API-key sources disabled pending key provisioning.
Confirm the list.

### Egress isolation
- [ ] Scraper uses dedicated `httpx.AsyncClient` that **refuses private IP
      ranges** (RFC1918, loopback, link-local IPv4 + IPv6). Prevents SSRF
      to internal services if a source ever redirects to `127.0.0.1` or
      `169.254.169.254`.

## Security notes
- SSRF guard: outbound only to public IPs.
- robots.txt honored; no override.
- Saved HTML named by content sha256; never trusting `Content-Disposition`.
- No JS executed against saved HTML in our UI; treated as data.
- No Playwright = removes a class of browser-CVE supply chain risk.

## Acceptance criteria
- [ ] Adding a source and clicking "Crawl now" produces `raw_pages` rows
      and enqueues parse jobs.
- [ ] robots-disallowed paths are skipped and logged.
- [ ] Re-crawl after 1 minute fetches 0 new pages.
- [ ] Egress to `127.0.0.1`, `169.254.169.254` rejected with clean error.
- [ ] A JS-heavy fixture site is fetched with `parse_status='needs_js_render'`;
      no crash, no halt of the source's other pages.

## Open questions for the user
- **Starter list approval** — trim or extend.
- **Eventbrite / Meetup keys** — provision now or defer? Big signal boost
  if enabled.

## Risks
- **Legal**: scraping is generally fine for public, robots-allowed pages
  with attribution. Per-source vetting checklist lives in step 29.
- **Coverage**: no Playwright means some sites we can't read. Acceptable.
  The diagnostics surface tells us which sources are blocked so we can
  decide whether to manually feed conference data instead.
