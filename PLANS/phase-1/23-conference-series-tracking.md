# 23 — Conference Series Tracking

## Goal
Link year-over-year editions of the same conference (NeurIPS 2025 ↔ NeurIPS
2026) into a **series** so we can:
- Show DAAM's historical attendance pattern on the detail page
- Power the past-attendance bonus in SME matching (step 18)
- Detect "same event, different year" in dedup (step 15) without false merges
- Surface "the series has trended away from our messaging over the years"

## Prereqs
- 04 (schema; this step adds the `conference_series` table)
- 15 (extraction populates new conferences we'll group)

## Schema additions
- [ ] New table `conference_series` (app schema):
  - `id uuid PK`
  - `canonical_name text UNIQUE` (e.g., "NeurIPS")
  - `aliases text[]` (e.g., `["Neural Information Processing Systems", "NIPS"]`)
  - `description text`
  - `typical_month smallint` (nullable, 1-12; e.g., NeurIPS ≈ 12)
  - `typical_topics text[]` (loose hints to bootstrap matching)
  - `homepage text`
  - `is_active boolean`
- [ ] Add `series_id uuid` (nullable, FK to `conference_series`) to `conferences`.
- [ ] Add `series_id uuid` (nullable, FK) to `past_conferences`.
- [ ] Alembic migration in step 06 is updated to include these.

## Pre-loaded known-series seed catalog
- [ ] Ship `db/seeds/conference_series.yaml` with ~50 major AI/ML/cloud/RH-adjacent
      conference series. Loaded as part of the initial migration's seed step (step 06).
- [ ] Curated content per series: `canonical_name`, `aliases`, `description`,
      `typical_month`, `typical_topics`, `homepage`. Examples:
  ```yaml
  - canonical_name: NeurIPS
    aliases: [Neural Information Processing Systems, NIPS]
    description: Top-tier ML research conference. Annual.
    typical_month: 12
    typical_topics: [machine learning, deep learning, neural networks, reinforcement learning]
    homepage: https://nips.cc
  - canonical_name: ICML
    aliases: [International Conference on Machine Learning]
    description: Top-tier ML research conference. Annual.
    typical_month: 7
    typical_topics: [machine learning, statistics]
    homepage: https://icml.cc
  - canonical_name: KubeCon + CloudNativeCon
    aliases: [KubeCon, CloudNativeCon]
    description: CNCF flagship event. North America (fall) + Europe (spring).
    typical_topics: [kubernetes, cloud native, containers, GitOps]
    homepage: https://events.linuxfoundation.org/kubecon-cloudnativecon
  # ... approx 50 entries: ACL, EMNLP, NAACL, ICLR, CVPR, ICCV, ECCV, KDD,
  # AAAI, WWW, SIGMOD, VLDB, OSDI, SOSP, USENIX ATC, KubeCon EU/NA,
  # Red Hat Summit, AnsibleFest, AI Engineer World's Fair, MLOps World,
  # Hugging Face events, Open Source Summit, Linux Plumbers, etc.
  ```
- [ ] Provides immediate value: Scout knows about major events from day 1.
      When the scraper finds "NeurIPS 2026", series linkage is a slam-dunk
      because the series already exists.
- [ ] The catalog is committed in git, reviewable as a PR, and editable by
      the team via the XLSX workbook (step 31's `Series` sheet — add it).

## Detection logic
- [ ] Manual: admin can create a series and assign conferences to it via the UI.
- [ ] Automated candidate suggestions (weekly cron `link_conference_series`, step 13):
  - For each new conference without `series_id`:
    - Strip year and edition markers from name (`NeurIPS 2025` → `NeurIPS`)
    - Fuzzy match (pg_trgm) against existing `conference_series.canonical_name` and `aliases`
    - If similarity > 0.85 → suggest link with confidence
    - If no match but multiple unlinked conferences share a stripped name → suggest new series
- [ ] Suggestions surface in `/settings/series` (review queue):
  - List of (conference, suggested_series, confidence) pairs
  - Approve / reject / create new series buttons
  - **No automatic linking** — series membership is too consequential for SME
    matching to assign without human confirmation

## Backend tasks
- [ ] `app/services/series/`:
  - `detector.py` — name stripping, candidate suggestion
  - `crud.py` — create/update/delete series; assign conference to series
- [ ] CRUD endpoints under `/api/v1/conference-series`:
  - GET list (with member conference counts)
  - GET one (with member conferences ordered by year)
  - POST create / PATCH update / DELETE deactivate
  - POST `/api/v1/conference-series/{id}/assign` (body: `conference_id`)
  - POST `/api/v1/conference-series/{id}/unassign`
- [ ] After series assignment, recompute matches for affected conferences
      (past-attendance bonus may shift).

## Frontend tasks
- [ ] `/settings/series` page:
  - List of series with year-range and member count
  - "Detect suggestions" button → table of (conference → suggested series + confidence)
  - Inline approve/reject; bulk approve "high confidence" (> 0.95)
  - "Create series manually" form (canonical name + initial members)
- [ ] On `/conferences/[id]` (step 20):
  - **"Previous editions" panel** showing prior conferences in this series
  - For each prior edition: name, year, DAAM attendees (chips), notes link
  - "This conference is not part of a series → Assign series" button if unlinked

## Graph integration (step 16)
- [ ] Add `ConferenceSeries` node type and `Conference -[:EDITION_OF]- Series` edge.
- [ ] Graph exploration (step 21) gains a "show series" toggle (default off; surfaces
      strong year-over-year clusters when on).

## SME matcher integration (step 18)
- [ ] `past_attendance_bonus`: instead of fuzzy-matching by conference name,
      consult `past_conferences.series_id`. SME has past attendance for this
      series → +0.1 bonus.

## Security notes
- Series assignments alter SME scores. Auditable via `audit_log` + `content_versions`.
- No PII surfaces in series-level views.
- Detector is rules + pg_trgm; no LLM, no untrusted output.

## Acceptance criteria
- [ ] Migration adds `conference_series` table and FKs without breaking existing data.
- [ ] Detector run produces sensible suggestions for a fixture set
      ("NeurIPS 2024", "NeurIPS 2025", "ICML 2024").
- [ ] Suggestions visible in `/settings/series`; approval creates the link.
- [ ] After linkage, conference detail page shows "Previous editions" panel.
- [ ] SME matcher uses `series_id` for past-attendance signal; recomputed
      after a new linkage.

## Open questions for the user
- **Auto-link high-confidence suggestions?** Recommend NO — keep human in the loop.
  Confirm.
- **Display year range** — show min-max only or full list per series? List for < 10, range otherwise.

## Risks
- False merges (mistaking "AI Summit" for "World AI Summit") would mislead SME
  recommendations. The human-in-loop gate prevents this.
- Renamed series (e.g., NIPS → NeurIPS) need their `aliases` populated. UI
  for editing aliases is part of the series detail page.
