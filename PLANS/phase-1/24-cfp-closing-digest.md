# 24 — CFP-Closing Digest

## Goal
Surface conferences with **upcoming CFP deadlines** so the team never misses
a submission window. The most operationally useful thing Scout can do day-to-day.

Daily scheduled job builds the digest; surfaced in a `/diagnostics` card,
a top-bar notification bell badge, and (optionally) a written copy the user
can paste into Slack/email.

## Prereqs
- 13 (scheduler)
- 17 (matches with overall_score exist for ranking)
- 20 (dashboard for the notification bell)

## Algorithm

Daily 09:00 (configurable TZ) cron job `build_cfp_digest`:

1. **Unnest `cfp_deadlines`** into one row per (conference, deadline). Each
   conference contributes multiple entries if it has early-bird + regular +
   workshop deadlines, etc.
2. Filter to deadlines where:
   - `date` within next 30 days
   - parent `conference.status` in (`discovered`, `needs_review`, `needs_review_pillar`, `needs_sme_review`, `approved`)
   - JOIN `matches` for `overall_score`
3. Bucket by window: 0–7 / 8–14 / 15–30 days.
4. Within each bucket, sort by `overall_score DESC` then `date ASC`.
5. Cap at 10 entries per bucket.
6. Build a `notifications` row of kind `cfp_digest` with payload:
   ```json
   {
     "generated_at": "...",
     "buckets": {
       "0_7":   [{conf_id, name, score, deadline_kind, deadline_date, top_sme_id, top_sme_name}, ...],
       "8_14":  [...],
       "15_30": [...]
     }
   }
   ```
   Each entry carries `deadline_kind` so the UI can show "**Workshop CFP** closes Sep 14"
   vs "**Regular CFP** closes Sep 14" — important distinction.
7. Mark previous unread `cfp_digest` notifications as `seen=true`.

## Backend tasks
- [ ] APScheduler cron registration in step 13.
- [ ] `app/services/digest/cfp.py` builder.
- [ ] `GET /api/v1/notifications` — paginated, filterable by kind.
- [ ] `GET /api/v1/notifications/latest?kind=cfp_digest` — convenience for the bell.
- [ ] `POST /api/v1/notifications/{id}/dismiss` — sets `seen=true`.
- [ ] Idempotent: re-running the digest on the same day overwrites the latest.
- [ ] Admin endpoint `POST /api/v1/admin/jobs/build_cfp_digest/trigger`
      (rate-limited 1/30s).

## Frontend tasks
- [ ] **Top-bar notification bell** (in the layout from step 08):
  - Badge count = unread notifications (initially just cfp_digest)
  - Click → dropdown showing the latest cfp digest
  - Each bucket as a small card; entries link to the conference detail
- [ ] **Dashboard `/dashboard` card**: "CFP closing soon" surface, expanded view
  - All three buckets visible
  - Quick-action: "Mark dismissed" / "View on conference page"
- [ ] **`/diagnostics`** shows when the digest last ran, how many entries, errors if any.
- [ ] **Optional copy-to-clipboard** button: formats the digest as Markdown
      for pasting into Slack/email:
  ```
  # Scout CFP Digest — 2026-05-21
  ## Closing this week
  - **NeurIPS 2026** (score 87) — CFP closes 2026-05-26; suggested SME: Sarah Chen
  ...
  ```

## Security notes
- Digest reads only from existing validated data; no new attack surface.
- Notifications table is per-install (single user); no cross-user leakage.
- Copy-to-clipboard runs client-side; no external posting.
- We do NOT send email/Slack from the app in Phase 1 (avoids credentials,
  SMTP, OAuth). Users do their own posting via copy-paste.

## Acceptance criteria
- [ ] Daily cron writes a `notifications` row at 09:00 local TZ.
- [ ] Bell badge shows count when an unread digest exists.
- [ ] Clicking the bell shows the latest digest with three buckets.
- [ ] Each entry links to the conference detail page.
- [ ] Copy-to-clipboard produces well-formed Markdown that pastes readably into Slack.
- [ ] Re-running on the same day replaces (does not duplicate) the latest digest.

## Open questions for the user
- **Email/Slack push for Phase 1?** Recommend NO (avoids credential ops);
  copy-to-clipboard is enough. Confirm.
- **Bucket windows** — `7/14/30` days. Other defaults preferred? Adjustable in env.
- **Cap of 10/bucket** — enough? Tunable in env.

## Risks
- "Score" is meaningful only if matcher quality is good. A high-score
  conference shown urgently helps; a misleading one hurts. The detail page's
  rationale + source links let the user verify quickly.
- Time zones. Scheduler TZ vs user's timezone — we render `cfp_close_at` in
  the user's local browser TZ; the cron uses `SCHEDULER_TIMEZONE` for the
  "send at 09:00" moment.
