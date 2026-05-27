/**
 * Scout API types — frontend mirror of the Pydantic schemas in
 * `apps/api/app/schemas/` (plan 05) and the matching routes (plan 09 backend).
 *
 * Hand-written for now so the SPA can compile against typed contracts before
 * the api is reachable from this build host. `pnpm gen:api` will replace this
 * file with one generated from /api/openapi.json — at which point the
 * hand-written types disappear and the autogen takes over.
 *
 * Until then, **keep this file in sync with `apps/api/app/schemas/` by hand
 * whenever you change a Pydantic schema or add a column to plan 04**.
 */

// ---------------------------------------------------------------------------
// Enums (mirror app/schemas/common.py)
// ---------------------------------------------------------------------------
export type RoleSeniority = "executive" | "director" | "manager" | "ic" | "mixed";
export type MessagingSourceType = "structured" | "pdf";
export type PastConferenceRole = "attendee" | "speaker" | "sponsor" | "organizer";
export type PastConferenceSessionType =
  | "keynote"
  | "talk"
  | "panel"
  | "workshop"
  | "poster";

// ---------------------------------------------------------------------------
// Shared shapes
// ---------------------------------------------------------------------------
/** Generic paginated response from any list endpoint. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
}

/** RFC 7807 problem+json — what the api returns on 4xx/5xx. */
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

// ---------------------------------------------------------------------------
// Messaging documents
// ---------------------------------------------------------------------------
export interface MessagingDocumentBase {
  title: string;
  source_type: MessagingSourceType;
  elevator_pitch: string;
  target_personas: string[];
  key_themes: string[];
  talking_points: string[];
  differentiators: string[];
  competitive_position: string;
  is_active: boolean;
}

export type MessagingDocumentCreate = MessagingDocumentBase;
export type MessagingDocumentUpdate = MessagingDocumentBase;

export interface MessagingDocumentRead extends MessagingDocumentBase {
  id: string;
  file_path: string | null;
  created_at: string; // ISO-8601
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Audience profiles
// ---------------------------------------------------------------------------
export interface AudienceProfileBase {
  name: string;
  description: string;
  industry: string;
  role_seniority: RoleSeniority;
  primary_pain_points: string[];
  key_messages: string[];
  exclusion_criteria: string[];
  is_active: boolean;
}

export type AudienceProfileCreate = AudienceProfileBase;
export type AudienceProfileUpdate = AudienceProfileBase;

export interface AudienceProfileRead extends AudienceProfileBase {
  id: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// SMEs
// ---------------------------------------------------------------------------
export interface SmeExternalLinks {
  linkedin?: string | null;
  github?: string | null;
  website?: string | null;
}

export interface SmeBase {
  full_name: string;
  email: string | null;
  team: string;
  expertise_areas: string[];
  primary_topics: string[]; // UUIDs
  audience_focus: string[];
  location_country: string;
  location_city: string | null;
  bio: string;
  languages: string[];
  external_links: SmeExternalLinks;
  is_active: boolean;
}

export type SmeCreate = SmeBase;
export type SmeUpdate = SmeBase;

export interface SmeRead extends SmeBase {
  id: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Past conferences
// ---------------------------------------------------------------------------
export interface PastConferenceBase {
  name: string;
  year: number;
  series_id: string | null;
  attended_sme_ids: string[];
  /** Raw attendee names from the source CSV — captures who actually
   * attended even if those people aren't SMEs in Scout yet. */
  attended_by_names_raw: string[];
  role: PastConferenceRole;
  session_type: PastConferenceSessionType | null;
  notes: string | null;
  imported_from: string | null;
}

export type PastConferenceCreate = PastConferenceBase;
export type PastConferenceUpdate = PastConferenceBase;

export interface PastConferenceRead extends PastConferenceBase {
  id: string;
  created_at: string;
  updated_at: string;
}

/** CSV import response from POST /api/v1/past-conferences/import */
export interface PastConferenceImportResult {
  imported: number;
  skipped: number;
  errors: Array<{ row: number; field: string; message: string }>;
  note?: string;
}

// ---------------------------------------------------------------------------
// Topics
// ---------------------------------------------------------------------------
export interface TopicBase {
  name: string;
  slug?: string | null;
  aliases: string[];
  is_active: boolean;
  pending_review: boolean;
}

export type TopicCreate = TopicBase;
export type TopicUpdate = TopicBase;

export interface TopicRead extends TopicBase {
  id: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Conferences + matcher output (plan 17/18/19 → plan 20 UI)
// ---------------------------------------------------------------------------
export type ConferenceStatus =
  | "discovered"
  | "needs_review"
  | "needs_review_pillar"
  | "needs_sme_review"
  | "approved"
  | "rejected"
  | "low_messaging_fit"
  | "quarantined";

export interface ConferenceRead {
  id: string;
  name: string;
  slug: string;
  status: string;
  confidence_score: number | null;
  start_date: string | null;
  end_date: string | null;
  location_city: string | null;
  location_country: string | null;
  latitude: number | null;
  longitude: number | null;
  is_virtual: boolean;
  website: string | null;
  cfp_url: string | null;
  topics: string[];
  cfp_topics_of_interest: string[];
  cfp_close_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConferenceListItem extends ConferenceRead {
  overall_score: number | null;
  messaging_score: number | null;
  pillar_score: number | null;
  sme_score: number | null;
  previously_attended: boolean;
}

export interface ConferenceListResponse {
  items: ConferenceListItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface MatchBoosts {
  cfp_urgency: number;
  recency_penalty: number;
  series_memory: number;
  flagship_event: number;
  total: number;
}

export interface ConferenceMatch {
  id: string;
  messaging_score: number;
  pillar_score: number;
  sme_score: number;
  judge_score: number | null;
  judge_rationale: string;
  overall_score: number;
  boosts: MatchBoosts;
  recommended_sme_ids: string[];
  rationale_text: string;
  computed_at: string | null;
}

export interface ConferenceMatchResponse {
  conference_id: string;
  algorithm_version: string;
  match: ConferenceMatch | null;
}

export interface ConferenceSourceRow {
  raw_page_id: string;
  url: string;
  fetched_at: string | null;
  http_status: number;
  parse_status: string | null;
  hash_prefix: string;
}

export interface ConferenceSourcesResponse {
  conference_id: string;
  sources: ConferenceSourceRow[];
}

export interface SmeDimensionScores {
  topic_overlap: number;
  audience_overlap: number;
  bio_similarity: number;
  location: number;
  past_attendance: number;
}

export interface SmeBreakdown {
  sme_id: string;
  full_name: string;
  team: string;
  location_country: string | null;
  location_city: string | null;
  is_external: boolean;
  dimensions: SmeDimensionScores;
  composite: number;
  above_gate: boolean;
  narrative?: string | null;
}

export interface ConferenceSmesResponse {
  conference_id: string;
  gate: number;
  weights: {
    topic: number;
    audience: number;
    bio: number;
    location: number;
    past: number;
  };
  narrative_top_k: number;
  above_gate: SmeBreakdown[];
  near_misses: SmeBreakdown[];
}

export type DecisionVerdict = "approved" | "rejected" | "needs_review";

export interface DecisionCreate {
  decision: DecisionVerdict;
  reason?: string | null;
  decided_by_label?: string;
}

export interface DecisionRead {
  id: string;
  conference_id: string;
  decision: string;
  reason: string | null;
  decided_by_label: string;
  decided_at: string;
  created_at: string;
}

export interface DecisionListResponse {
  conference_id: string;
  decisions: DecisionRead[];
}

// ---------------------------------------------------------------------------
// Knowledge graph (plan 16 → plan 21 explorer)
// ---------------------------------------------------------------------------
export type GraphNodeKind =
  | "conference"
  | "topic"
  | "sme"
  | "audience"
  | "pillar"
  | "messaging"
  | "source"
  | "series";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  degree?: number;
  // Per-kind optional metadata surfaced by the loader.
  status?: string;
  slug?: string;
  team?: string;
  start_date?: string | null;
  confidence?: number | null;
  is_active?: boolean;
  pending_review?: boolean;
  industry?: string;
  role_seniority?: string;
  display_order?: number;
  source_kind?: string;
}

export interface GraphLink {
  source: string;
  target: string;
  relation: string;
  weight?: number;
}

export interface GraphResponse {
  nodes: GraphNode[];
  links: GraphLink[];
  stats: {
    n_nodes: number;
    n_edges: number;
    truncated: boolean;
  };
}

// ---------------------------------------------------------------------------
// Diagnostics (plan 26)
// ---------------------------------------------------------------------------
export interface DiagnosticsResponse {
  generated_at: string;
  cache_ttl_seconds: number;
  llm: {
    month_to_date: { calls: number; tokens: number; cost_usd: number };
    last_24h: { calls: number; tokens: number; cost_usd: number };
    budget: {
      limit_usd: number | null;
      spent_usd: number;
      pct_used: number | null;
      threshold_warn: boolean;
    };
    by_purpose_24h: Array<{
      purpose: string;
      calls: number;
      tokens: number;
      cost_usd: number;
    }>;
    recent_errors: Array<{
      at: string | null;
      model: string;
      purpose: string;
      error: string;
    }>;
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
      no_topics: number;
      no_audiences: number;
      short_bio: number;
    };
    audiences_active: number;
    pending_topics: number;
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

// ---------------------------------------------------------------------------
// Notifications (plan 24)
// ---------------------------------------------------------------------------
export interface NotificationRead {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  seen: boolean;
  created_at: string;
}

export interface NotificationsList {
  items: NotificationRead[];
  total: number;
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

export interface CfpDigestPayload {
  generated_at: string;
  buckets: {
    "0_7"?: CfpDigestEntry[];
    "8_14"?: CfpDigestEntry[];
    "15_30"?: CfpDigestEntry[];
  };
  stats?: Record<string, number>;
}

export interface CfpDigestMarkdown {
  markdown: string;
  generated_at: string;
  n_entries: number;
}

// ---------------------------------------------------------------------------
// Agent chat (plan 22)
// ---------------------------------------------------------------------------
export interface AgentSession {
  id: string;
  title: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
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

export interface AgentCitation {
  index: number;
  chunk_id: string;
  owner_type: string;
  owner_id: string;
  label: string;
  similarity: number;
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

export interface DashboardStats {
  cards: {
    upcoming_approved: number;
    pending_review: number;
    cfp_closing_soon: number;
    low_coverage_smes: number;
  };
  top_conferences: Array<{
    id: string;
    name: string;
    slug: string;
    status: string;
    overall_score: number | null;
    start_date: string | null;
  }>;
}

// ---------------------------------------------------------------------------
// Conference create (manual entry)
// ---------------------------------------------------------------------------
export interface ConferenceCreate {
  name: string;
  start_date?: string | null; // ISO date YYYY-MM-DD
  end_date?: string | null;
  location_city?: string | null;
  location_country?: string | null; // ISO-3166-1 alpha-2
  is_virtual?: boolean;
  venue?: string | null;
  website?: string | null;
  cfp_open_at?: string | null;
  cfp_close_at?: string | null;
  cfp_topics_of_interest?: string[];
  topics?: string[];
  acceptance_rate_percent?: number | null;
  estimated_cost_usd?: number | null;
  actor_label?: string;
}

export interface ConferenceCreateResponse {
  conference: import("@/lib/api-types").ConferenceRead;
  match: {
    overall_score: number;
    messaging_score: number;
    pillar_score: number;
    sme_score: number;
    status: string;
    rationale_text: string;
    recommended_sme_ids: string[];
    matched_pillar_name: string | null;
  } | null;
  match_error: string | null;
}

// ---------------------------------------------------------------------------
// Team recommendations (plan 32)
// ---------------------------------------------------------------------------
export interface TeamPickRead {
  team_size: number;
  sme_ids: string[];
  team_score: number;
  coverage_breadth: number;
  redundancy: number;
  rationale_text: string;
  computed_at: string | null;
}

export interface TeamRecommendationsResponse {
  conference_id: string;
  algorithm_version?: string;
  by_size: Record<string, TeamPickRead>;
}

// ---------------------------------------------------------------------------
// Brief (plan 33)
// ---------------------------------------------------------------------------
export interface BriefAttendee {
  sme_id: string;
  full_name: string;
  team: string;
  location_city: string | null;
  location_country: string | null;
  expertise_areas: string[];
  bio: string;
  narrative: string;
}

export interface BriefDeadline {
  kind: string | null;
  date: string | null;
  description: string | null;
  days_remaining: number | null;
  is_next: boolean;
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
    messaging_score: number | null;
    pillar_score: number | null;
    sme_score: number | null;
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
    freshness_score: number | null;
  };
  why: {
    rationale_text: string;
    matched_pillar: {
      name: string;
      description: string;
      score: number | null;
    } | null;
    top_topics: Array<{ name: string; slug: string; weight: number | null }>;
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
  logistics_placeholder: {
    storage_key: string;
    fields: string[];
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
