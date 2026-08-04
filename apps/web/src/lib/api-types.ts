/**
 * The SPA's view of the API contract.
 *
 * WHAT THIS IS
 *   A thin facade over `api-schema.ts`, which is GENERATED from the live
 *   server by `pnpm gen:api` and must never be hand-edited. Everything in
 *   the first block below is re-exported straight from the server's own
 *   OpenAPI schema, so a renamed or removed field is a TypeScript error
 *   here rather than an `undefined` at runtime.
 *
 * WHY IT EXISTS
 *   `openapi-typescript` emits `components["schemas"]["Foo"]`, but ~50
 *   files already import a flat `Foo`. The facade bridges the two without
 *   touching every call site.
 *
 * HISTORY WORTH KNOWING
 *   This file used to be 934 hand-written lines whose own header said
 *   `pnpm gen:api` would replace it — except gen:api pointed at
 *   `../api/openapi.json`, which never existed, so it had never once been
 *   runnable. It was typing a `fetch` cast, not a contract: six pillar
 *   endpoints stayed in the client long after a migration dropped the
 *   tables underneath them, and nothing complained.
 */

import type { components } from "./api-schema";

type S = components["schemas"];

export type { components } from "./api-schema";

/* ------------------------------------------------------------------ *
 * Derived from the server. Add nothing here by hand — regenerate.
 * ------------------------------------------------------------------ */

export type AudienceProfileCreate = S["AudienceProfileCreate"];
export type AudienceProfileRead = S["AudienceProfileRead"];
export type AudienceProfileUpdate = S["AudienceProfileUpdate"];
export type ConferenceCreate = S["ConferenceCreate"];
export type ConferenceCreateResponse = S["ConferenceCreateResponse"];
export type ConferenceListResponse = S["ConferenceListResponse"];
export type ConferenceMatchResponse = S["ConferenceMatchResponse"];
export type ConferenceRead = S["ConferenceRead"];
export type ConferenceSmesResponse = S["ConferenceSmesResponse"];
export type ConferenceTalksResponse = S["ConferenceTalksResponse"];
export type ImportColumnSpec = S["ImportColumnSpec"];
export type ImportResult = S["ImportResult"];
export type AnalyticsOverview = S["AnalyticsOverview"];
export type PillarAnalytics = S["PillarAnalytics"];
export type PillarConferenceItem = S["PillarConferenceItem"];
export type SmeAnalytics = S["SmeAnalytics"];
export type DashboardStats = S["DashboardStats"];
export type DecisionCreate = S["DecisionCreate"];
export type DecisionRead = S["DecisionRead"];
export type MessagingDocUploadPreview = S["MessagingDocUploadPreview"];
export type MessagingUploadStatus = S["MessagingUploadStatus"];
export type MessagingDocumentCreate = S["MessagingDocumentCreate"];
export type MessagingDocumentRead = S["MessagingDocumentRead"];
export type MessagingDocumentUpdate = S["MessagingDocumentUpdate"];
export type NotificationRead = S["NotificationRead"];
export type NotificationsList = S["NotificationsList"];
export type PillarCreate = S["PillarCreate"];
export type PillarRead = S["PillarRead"];
export type PillarUpdate = S["PillarUpdate"];
export type ReuseCheckResult = S["ReuseCheckResult"];
export type RoleSeniority = S["RoleSeniority"];
export type SmeCreate = S["SmeCreate"];
export type SmePillarLink = S["SmePillarLink"];
export type SmePillarRead = S["SmePillarRead"];
export type SmeRead = S["SmeRead"];
export type SmeUpdate = S["SmeUpdate"];
export type TalkCreate = S["TalkCreate"];
export type TalkRead = S["TalkRead"];
export type TalkSubmissionCreate = S["TalkSubmissionCreate"];
export type TalkSubmissionRead = S["TalkSubmissionRead"];
export type TalkUpdate = S["TalkUpdate"];
export type TalkUploadPreview = S["TalkUploadPreviewBody"];
export type TalkUploadStatus = S["TalkUploadStatus"];

/* ------------------------------------------------------------------ *
 * NOT on the server yet.
 *
 * Each of these describes a response whose route is annotated `-> dict`,
 * so FastAPI publishes `additionalProperties: true` and promises nothing.
 * They are hand-maintained and WILL drift — that is not a style problem,
 * it is the exact failure this file was rewritten to end.
 *
 * The fix is a `response_model` on the route, after which the type moves
 * into the generated block above and its definition here is deleted.
 * Tracked as F1.
 * ------------------------------------------------------------------ */

export interface AgentCitation {
  index: number;
  chunk_id: string;
  owner_type: string;
  owner_id: string;
  label: string;
  similarity: number;
}

export interface AgentMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata_json: {
    prompt_version?: string;
    citations?: AgentCitation[];
    n_snippets?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    cost_usd?: number;
    latency_ms?: number;
  };
  created_at: string;
}

export interface AgentReply {
  session_id: string;
  user_message_id: string;
  assistant_message_id: string;
  role: "assistant";
  content: string;
  citations: AgentCitation[];
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  prompt_version: string;
}

export interface AgentSession {
  id: string;
  title: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApiProblem {
  type: string;
  title: string;
  status: number;
  detail: string;
  errors?: Array<{
    loc: (string | number)[];
    msg: string;
    type?: string;
    [k: string]: unknown;
  }>;
  [k: string]: unknown;
}

export interface CfpDigestEntry {
  conference_id: string;
  name: string;
  slug: string;
  status: string;
  overall_score: number | null;
  deadline_kind: string;
  deadline_date: string;
  days_until: number;
  top_sme_id: string | null;
  top_sme_name: string | null;
  website: string | null;
  location: string | null;
}

export interface CfpDigestMarkdown {
  markdown: string;
  generated_at: string;
  n_entries: number;
}

export interface CfpDigestPayload {
  generated_at: string;
  buckets: {
    today?: CfpDigestEntry[];
    tomorrow?: CfpDigestEntry[];
  };
  stats?: Record<string, number>;
}

export interface ConferenceBrief {
  conference_id: string;
  generated_at: string;
  algorithm_version: string;
  scout_version: string;
  team_size: number;
  header: {
    name: string;
    slug: string;
    start_date: string | null;
    end_date: string | null;
    location_city: string | null;
    location_country: string | null;
    is_virtual: boolean;
    venue: string | null;
    website: string | null;
  };
  at_a_glance: {
    overall_score: number | null;
    // The matcher asks two questions, not three. `messaging_score`,
    // `pillar_score` and `sme_score` were the old three-stage names;
    // messaging and pillars are pooled into `fit` and rescaled once.
    fit_score: number | null;
    speaker_score: number | null;
    overall_bucket: "strong" | "good" | "marginal" | "weak" | null;
    status: string;
    acceptance_rate_percent: number | null;
    estimated_cost_usd: number | null;
    series: {
      id: string;
      canonical_name: string;
      typical_month: number | null;
      past_editions_count: number;
      team_attended_recent: number;
    } | null;
  };
  why: {
    rationale_text: string;
    matched_pillar: {
      name: string;
      description: string;
      score: number | null;
    } | null;
    top_topics: Array<{ name: string; slug?: string; weight?: number | null }>;
  };
  attendees: {
    team_size: number;
    members: BriefAttendee[];
    rationale_text: string;
    source: "team_rec" | "individual_fallback" | "empty" | "none";
  };
  cfp: {
    deadlines: BriefDeadline[];
    topics_of_interest: string[];
    open_at: string | null;
    close_at: string | null;
  };
  past_engagement: Array<{
    name: string;
    year: number;
    role: string;
    session_type: string | null;
    notes: string;
    attendees: Array<{ sme_id: string; full_name: string }>;
  }>;
  talking_points: Array<{
    document_id: string;
    title: string;
    elevator_pitch: string;
    talking_points: string[];
    key_themes: string[];
    similarity: number;
  }>;
  /** Trip logistics; free-text status per leg. Verified present in the
   *  live payload from `build_brief`. */
  logistics: {
    travel: string;
    lodging: string;
    booth: string;
    sponsorship: string;
  };
  footer: {
    detail_url_path: string;
    decision: {
      decision: string;
      decided_by_label: string;
      decided_at: string | null;
      reason: string | null;
    } | null;
    sources_count: number;
  };
}

export interface ConferenceSourcesResponse {
  conference_id: string;
  sources: ConferenceSourceRow[];
}

export interface DecisionListResponse {
  conference_id: string;
  decisions: DecisionRead[];
}

export type DecisionVerdict = "approved" | "rejected" | "needs_review";

export interface DiagnosticsResponse {
  generated_at: string;
  cache_ttl_seconds: number;
  usage: {
    conferences_by_status: Record<string, number>;
    conferences_scored: number;
    decisions: { "7d": number; "30d": number; all: number };
    decisions_by_outcome: {
      "7d": Record<string, number>;
      "30d": Record<string, number>;
      all: Record<string, number>;
    };
    talk_submissions_total: number;
    conferences_attended: number;
    conferences_attended_scored: number;
    smes_active: number;
  };
  llm: {
    calls: { "24h": number; "7d": number; "30d": number; all: number };
    calls_24h_ok: number;
    calls_24h_errors: number;
    last_success: {
      at: string | null;
      model: string;
      purpose: string;
      latency_ms: number | null;
    } | null;
    errors_cleared_at: string | null;
    by_purpose_24h: Array<{ purpose: string; calls: number }>;
    recent_errors: Array<{
      at: string | null;
      model: string;
      purpose: string;
      error: string;
    }>;
    connectivity: {
      endpoint: LlmEndpointProbe;
      embedding_endpoint: LlmEndpointProbe | null;
      chat_model_available: boolean | null;
      embedding_model_available: boolean | null;
      config: {
        base_url: string;
        chat_model: string;
        embedding_model: string;
        dry_run: boolean;
        api_key_masked: string | null;
        api_key_source: "db_override" | "env";
        embedding_key_set: boolean;
      };
    };
  };
  jobs: {
    running: Array<{
      id: string;
      kind: string;
      started_at: string | null;
      elapsed_seconds: number | null;
    }>;
    failed_24h: Array<{
      id: string;
      kind: string;
      started_at: string | null;
      finished_at: string | null;
      error_preview: string | null;
    }>;
    by_kind_24h: Record<string, Record<string, number>>;
    next_fires: Array<{
      id: string;
      name: string;
      next_run_time: string | null;
    }>;
  };
  scraper: {
    sources: Array<{
      id: string;
      name: string;
      kind: string;
      enabled: boolean;
      robots_allowed: boolean;
      last_crawled_at: string | null;
      pages_fetched: number;
      politeness_delay_seconds: number;
    }>;
    js_blocked_pages: number;
    disabled_sources: Array<{ id: string; name: string }>;
  };
  data: {
    conferences_by_status: Record<string, number>;
    smes: {
      total_active: number;
      no_audiences: number;
      short_bio: number;
    };
    audiences_active: number;
    series: { active_count: number; unlinked_conferences: number };
    embedding_model: {
      name: string;
      dimension: number;
      provider: string;
    } | null;
    freshness_histogram: {
      buckets: number;
      edges: number[];
      counts: number[];
      total: number;
    };
    decay_enabled: boolean;
  };
  digest: {
    latest:
      | {
          id: string;
          created_at: string;
          generated_at: string | null;
          seen: boolean;
          bucket_counts: Record<string, number>;
          total_entries: number;
        }
      | null;
  };
  system: {
    postgres: {
      version: string;
      db_size_pretty: string;
      db_size_bytes: number;
    };
    storage_path: string;
    disk_usage: {
      path: string;
      total_bytes: number;
      used_bytes: number;
      free_bytes: number;
    } | null;
    process_started_at: string | null;
    uptime_seconds: number | null;
    env: string;
  };
}

export interface DiagnosticsRetryResponse {
  queued_job_id: string;
  original_ingest_job_id: string;
  kind: string;
}

export type DocKind = "gtm_strategy" | "content_roadmap" | "other";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
}

export interface PillarAudienceItem {
  id: string;
  name: string;
  description: string;
}


export interface PillarTalkItem {
  id: string;
  title: string;
  review_status: TalkReviewStatus;
}



export type TalkFormat = "keynote" | "talk" | "panel" | "workshop" | "tutorial" | "other";

export type TalkReviewStatus = "draft" | "pending_review" | "approved";




/**
 * One person on the trip.
 *
 * This used to describe a RECOMMENDED SME (full_name, team, bio,
 * narrative). The brief's attendees section was changed to report who is
 * actually going — participation rows — and the type was never updated,
 * so every field the page read was invisible to the compiler. Verified
 * against the live payload from `_attendees_section` in
 * apps/api/app/services/reports.py.
 */
export interface BriefAttendee {
  person_label: string;
  sme_id: string | null;
  activity: string | null;
  arrives_on: string | null;
  departs_on: string | null;
  /** Derived: an explicit attended mark, or departure already in the past. */
  has_attended: boolean;
  notes: string | null;
}

export interface BriefDeadline {
  kind: string | null;
  date: string | null;
  description: string | null;
  days_remaining: number | null;
  is_next: boolean;
}

export interface ConferenceSourceRow {
  raw_page_id: string;
  url: string;
  fetched_at: string | null;
  http_status: number;
  parse_status: string | null;
  hash_prefix: string;
}

export interface LlmEndpointProbe {
  ok: boolean;
  status_code: number | null;
  latency_ms: number;
  error: string | null;
  available_models: string[] | null;
}




export type ConferenceListItem = S["ConferenceListItem"];





export type SettingsResponse = S["SettingsResponse"];

export type SettingSpec = S["SettingSpec"];

/* These are published by the server now (F1) — aliased, not hand-written. */
export type ConferenceMatch = S["MatchRead"];
export type SmeBreakdown = S["SmeBreakdownRead"];
