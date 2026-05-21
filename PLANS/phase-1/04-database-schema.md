# 04 — Database Schema

## Goal
Design the relational schema. Load-bearing for every later step. Single-user
local install — no users table, no per-actor attribution beyond a free-form
`actor_label`. Schema enforces strict types so the input guardrails (step 05)
have a foundation to validate against.

## Prereqs
- 03 (Postgres up)
- 06 will codify this as the initial Alembic migration

## Conventions
- `id uuid PRIMARY KEY DEFAULT gen_random_uuid()` on every table.
- `created_at`, `updated_at` `timestamptz NOT NULL DEFAULT now()`.
- No `created_by` / `updated_by` (no users). Use `actor_label TEXT` where attribution matters.
- Soft deletes via `is_active boolean`. Never hard-delete.
- Snake_case everywhere.
- **Prefer typed columns over freeform JSON.** JSON columns only where the
  shape is genuinely open (LLM tool outputs, raw scrape stats). User-input
  schemas (messaging, audiences, SMEs) are fully typed.

## Schema overview

### Manual inputs (`app` schema) — fully typed
- [ ] `messaging_documents`
      `title`, `source_type` (`pdf`/`structured`), `file_path` (nullable for structured),
      `elevator_pitch text`, `target_personas text[]`, `key_themes text[]`,
      `talking_points text[]`, `differentiators text[]`, `competitive_position text`,
      `raw_content text` (only populated for PDF source for embedding),
      `is_active`.
- [ ] `audience_profiles`
      `name unique`, `description`,
      `industry text`, `role_seniority text` (enum: `executive`/`director`/`manager`/`ic`/`mixed`),
      `primary_pain_points text[]`, `key_messages text[]`, `exclusion_criteria text[]`,
      `is_active`.
- [ ] `strategic_pillars`
      `name`, `description`, `display_order`. Seeded.
- [ ] `smes`
      `full_name`, `email` (optional, for past-conference matching),
      `team text` (`DAAM` or other team name),
      `expertise_areas text[]`,
      `primary_topics uuid[]` (FK to `topics`; junction table also exists for graph),
      `audience_focus uuid[]` (FK to `audience_profiles`),
      `location_country char(2)` (ISO-3166-1 alpha-2),
      `location_city text`,
      `bio text` (≤2000 chars, validated),
      `languages text[]`,
      `external_links jsonb` (limited keys; see guardrails step 05),
      `is_active`.
- [ ] `past_conferences`
      `name`, `year smallint`,
      `series_id uuid` (nullable, FK to `conference_series` from step 23 once that lands),
      `attended_sme_ids uuid[]`,
      `role text` (enum: `attendee`/`speaker`/`sponsor`/`organizer`),
      `session_type text` (nullable enum: `keynote`/`talk`/`panel`/`workshop`/`poster`),
      `notes text` (≤500 chars),
      `imported_from text`.

### Discovered data (`app`)
- [ ] `sources`
      `name`, `url`, `kind` (`rss`/`sitemap`/`page`/`api`), `enabled boolean`,
      `last_crawled_at timestamptz`, `crawl_cadence interval`,
      `robots_allowed boolean`, `politeness_delay_seconds smallint`,
      `notes text`.
- [ ] `raw_pages`
      `source_id`, `url`, `fetched_at`, `http_status smallint`,
      `content_type text`, `raw_body_path text`, `hash text UNIQUE`,
      `etag text`, `last_modified text`.
- [ ] `conferences`
      `name`, `slug text UNIQUE`,
      `start_date date`, `end_date date`,
      `location_city text`, `location_country char(2)`,
      `is_virtual boolean`, `venue text`, `website text`,
      `cfp_open_at date`, `cfp_close_at date` (kept as denormalized "primary"
         deadline for fast queries; sourced from `cfp_deadlines[0]` or earliest),
      `cfp_deadlines jsonb` — array of `{kind, date, description, applies_to}`
         where `kind` enum: `early_bird`/`regular`/`late`/`workshop`/`camera_ready`/`registration`,
         supports the multi-deadline reality of real conferences,
      `cfp_topics_of_interest text[]` — distinct from general `topics`;
         captures the conference's explicit "topics we want submissions on" list.
         Used by the matcher to boost conferences whose solicited topics
         align with our expertise, not just the conference's general theme,
      `acceptance_rate_percent smallint` (nullable; extracted where available),
      `estimated_cost_usd integer`,
      `topics text[]` (denormalized for filtering; junction is authoritative),
      `confidence_score real`,
      `status text` (enum:
         `discovered`/`needs_review`/`needs_review_pillar`/`needs_sme_review`/
         `low_messaging_fit`/`approved`/`rejected`/`quarantined`/`archived`),
      `freshness_score real` (step 25 decay).
- [ ] `conference_sources` — many-to-many; which raw_pages contributed.
- [ ] `topics` — controlled vocabulary.
      `name text UNIQUE`, `slug text UNIQUE`, `aliases text[]`,
      `is_active boolean`, `pending_review boolean`.

### Junction tables (the "graph") — `app`
NetworkX (step 16) loads from these.
- [ ] `conference_topics` (`conference_id`, `topic_id`, `weight real`)
- [ ] `conference_audiences` (`conference_id`, `audience_id`, `weight real`)
- [ ] `conference_pillars` (`conference_id`, `pillar_id`, `score real`)
- [ ] `conference_smes` (`conference_id`, `sme_id`, `score real`) — computed
- [ ] `sme_topics` (`sme_id`, `topic_id`, `weight real`)
- [ ] `sme_audiences` (`sme_id`, `audience_id`, `weight real`)
- [ ] `messaging_pillars` (`messaging_document_id`, `pillar_id`, `weight real`)

### Vectors (`vectors`)
- [ ] `document_chunks`
      `id`, `owner_type` (enum: `messaging`/`audience`/`conference`/`sme_bio`/`raw_page`),
      `owner_id`, `chunk_index`, `text`, `token_count`,
      `embedding_model_id`, `embedding vector(768)`, `last_used_at`,
      `chunk_metadata jsonb` — Docling-produced structural info captured during
      chunking: `{section_heading, page_number, content_type, ...}` where
      `content_type` is `prose`/`table`/`list`/`heading`/`other`. Powers
      citation in the agent chat (plan 22) — "see page 4, table 'Audience profiles'"
      instead of "see chunk 17". Empty object `{}` for non-document inputs.
- [ ] `embedding_models`
      `name`, `provider`, `dimension`, `is_active`, `deprecated_at`.

### Match & decision (`app`)
- [ ] `matches`
      `conference_id`, `messaging_score real`, `pillar_score real`, `sme_score real`,
      `overall_score real`, `recommended_sme_ids uuid[]`,
      `rationale_text text`,
      `sme_fit_narratives jsonb` (keyed by sme_id; step 19 populates),
      `algorithm_version text`, `computed_at`.
- [ ] `decisions`
      `conference_id`, `decided_by_label text`, `decision text` (enum),
      `reason text`, `decided_at`.

### Operational
- [ ] `audit_log` (audit) — append-only.
      `actor_label`, `action`, `target_type`, `target_id`,
      `before jsonb`, `after jsonb`, `at`.
- [ ] `ingest_jobs` (app)
      `kind`, `status`, `started_at`, `finished_at`, `stats jsonb`, `error_text`.
- [ ] `content_versions` (audit) — for "git blame" (step 25).
      `entity_type`, `entity_id`, `version_number`, `diff jsonb`,
      `actor_label`, `changed_at`, `reason text`.
- [ ] `llm_calls` (app)
      `model`, `purpose`, `prompt_tokens`, `completion_tokens`, `cost_usd`,
      `latency_ms`, `request_id`, `error`.
- [ ] `chat_sessions`, `chat_messages` (app) — for agent chat (step 22).
- [ ] `notifications` (app) — for CFP digest (step 24).
      `kind`, `payload jsonb`, `seen boolean`, `created_at`.

## Indexes (initial)
- [ ] `conferences (slug)` UNIQUE
- [ ] `conferences (start_date)`
- [ ] `conferences (status, start_date)` partial for active statuses
- [ ] `raw_pages (hash)` UNIQUE
- [ ] `raw_pages (url, fetched_at DESC)`
- [ ] GIN on `conferences.topics`
- [ ] HNSW on `document_chunks.embedding` with `vector_cosine_ops` (step 11)
- [ ] `audit_log (at DESC)`
- [ ] `notifications (seen, created_at DESC)`

## Security notes
- `audit_log` immutability enforced at the role level — `app` has INSERT + SELECT only.
- No PII columns beyond name + city + country on SMEs (email optional, only if user provides).
- Free-form `actor_label` is user-typed; never validated as identity.
- `external_links jsonb` on SMEs is constrained to known keys via Pydantic
  validation in step 05; the DB accepts the type but the API rejects shapes.

## Tasks
- [ ] Mermaid ERD in `docs/erd.md`.
- [ ] Initial Alembic migration (created in step 06) encodes everything above.
- [ ] Seed migration: `strategic_pillars` (text from user), starter `audience_profiles`,
      `embedding_models` row for `nomic-embed-text-v1.5` (768 dim, active).

## Acceptance criteria
- [ ] `alembic upgrade head` from empty DB creates every table cleanly.
- [ ] `alembic downgrade base` reverses cleanly.
- [ ] ERD reflects schema 1:1.
- [ ] After migrate+seed: four pillars present, one embedding model registered.
- [ ] `app` role cannot DELETE from `audit_log`.
- [ ] Every text field has a length cap matching the guardrails in step 05.

## Open questions for the user
- **Four-pillar wording** — exact text for seed data.
- **Audience `industry`** — controlled enum, or freeform string? Recommend controlled enum populated by you.
- **`estimated_cost_usd` scope** — registration only or all-in? Affects extraction prompt.

## Risks
- Schema churn once conferences flow. `audit_log` + `content_versions` let us
  evolve safely, but `conferences` is painful to migrate. Get its fields
  right before step 15 ships.
