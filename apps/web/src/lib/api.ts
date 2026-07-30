/**
 * Typed API client.
 *
 * Thin wrapper around fetch() that returns typed JSON and surfaces
 * RFC 7807 problem+json errors via the ApiError class. Each resource
 * gets a small grouped helper at the bottom — kept small here so per-feature
 * code can compose its own React Query hooks.
 *
 * Origin: same-origin in production (api serves the SPA from /static); the
 * Vite dev server proxies /api to localhost:8000.
 */

import type {
  AnalyticsOverview,
  SettingsResponse,
  AgentMessage,
  AgentReply,
  AgentSession,
  ApiProblem,
  AudienceProfileCreate,
  AudienceProfileRead,
  AudienceProfileUpdate,
  TalkUploadPreview,
  ConferenceBrief,
  ConferenceCreate,
  ConferenceCreateResponse,
  ConferenceListResponse,
  ConferenceMatchResponse,
  ConferenceSmesResponse,
  ConferenceSourcesResponse,
  ConferenceTalksResponse,
  DashboardStats,
  DecisionCreate,
  DecisionListResponse,
  DecisionRead,
  CfpDigestMarkdown,
  DiagnosticsResponse,
  DiagnosticsRetryResponse,
  MessagingDocUploadPreview,
  MessagingDocumentCreate,
  MessagingDocumentRead,
  MessagingDocumentUpdate,
  NotificationRead,
  NotificationsList,
  Page,
  PillarAudienceItem,
  PillarAnalytics,
  PillarConferenceItem,
  PillarCreate,
  PillarRead,
  PillarTalkItem,
  PillarUpdate,
  ReuseCheckResult,
  SmeAnalytics,
  SmeCreate,
  SmeRead,
  SmeUpdate,
  SmePillarLink,
  SmePillarRead,
  TalkCreate,
  TalkRead,
  TalkSubmissionCreate,
  TalkSubmissionRead,
  TalkUpdate,
} from "@/lib/api-types";

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ApiProblem;

  constructor(problem: ApiProblem) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.problem = problem;
  }

  /** Convenience: maps validation errors to a {field: message} dict for form rendering. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const err of this.problem.errors ?? []) {
      // Pydantic gives loc as ['body', 'field_name']; we strip the prefix.
      const path = err.loc.filter((p) => p !== "body").join(".");
      if (path) out[path] = err.msg;
    }
    return out;
  }
}

// ---------------------------------------------------------------------------
// Core request helper
// ---------------------------------------------------------------------------
type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

type QueryValue = string | number | boolean | null | undefined | string[] | number[];

interface RequestOptions {
  method?: Method;
  query?: Record<string, QueryValue>;
  body?: unknown;
  /** Pass a FormData instance for multipart uploads; bypasses JSON encoding. */
  form?: FormData;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, form, signal } = options;

  const url = new URL(path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      if (Array.isArray(v)) {
        // FastAPI repeats: ?k=a&k=b. Single comma-joined value would be
        // interpreted as one literal string.
        for (const item of v) {
          if (item !== undefined && item !== null && item !== "") {
            url.searchParams.append(k, String(item));
          }
        }
      } else {
        url.searchParams.set(k, String(v));
      }
    }
  }

  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (form) {
    payload = form;
    // do NOT set Content-Type; the browser sets it with boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const init: RequestInit = { method, headers };
  if (payload !== undefined) init.body = payload;
  if (signal !== undefined) init.signal = signal;
  const res = await fetch(url.toString(), init);

  if (res.status === 204) {
    return undefined as T;
  }

  const ct = res.headers.get("content-type") ?? "";
  const isJson = ct.includes("application/json") || ct.includes("application/problem+json");

  if (!res.ok) {
    let problem: ApiProblem;
    if (isJson) {
      problem = (await res.json()) as ApiProblem;
    } else {
      problem = {
        type: "about:blank",
        title: res.statusText || "Error",
        status: res.status,
        detail: await res.text(),
      };
    }
    throw new ApiError(problem);
  }

  return isJson ? ((await res.json()) as T) : (undefined as T);
}

// ---------------------------------------------------------------------------
// Resource-grouped helpers
// ---------------------------------------------------------------------------
// Pattern: each group has list/get/create/update/deactivate. Keep the
// helpers thin — feature code wraps them in React Query hooks.

const BASE = "/api/v1";

type ListParams = {
  page?: number;
  per_page?: number;
  q?: string;
  is_active?: boolean | null;
  pillar_id?: string | null;
};

export const messagingApi = {
  /** Undo a deactivate — see smesApi.restore for why this exists. */
  restore: (doc: MessagingDocumentRead, actor_label = "system") =>
    request<MessagingDocumentRead>(`${BASE}/messaging-documents/${doc.id}`, {
      method: "PUT",
      query: { actor_label },
      body: { ...doc, is_active: true },
    }),
  list: (params: ListParams & { pillar_id?: string } = {}) =>
    request<Page<MessagingDocumentRead>>(`${BASE}/messaging-documents`, { query: params }),
  get: (id: string) => request<MessagingDocumentRead>(`${BASE}/messaging-documents/${id}`),
  create: (body: MessagingDocumentCreate, actor_label = "system") =>
    request<MessagingDocumentRead>(`${BASE}/messaging-documents`, {
      method: "POST",
      body,
      query: { actor_label },
    }),
  update: (id: string, body: MessagingDocumentUpdate, actor_label = "system") =>
    request<MessagingDocumentRead>(`${BASE}/messaging-documents/${id}`, {
      method: "PUT",
      body,
      query: { actor_label },
    }),
  deactivate: (id: string, actor_label = "system") =>
    request<void>(`${BASE}/messaging-documents/${id}`, {
      method: "DELETE",
      query: { actor_label },
    }),
  uploadPreview: async (file: File, doc_kind: string): Promise<MessagingDocUploadPreview> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/messaging-documents/upload?doc_kind=${encodeURIComponent(doc_kind)}`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const detail = (data as { detail?: string }).detail ?? `HTTP ${res.status}`;
      throw new ApiError({ type: "about:blank", status: res.status, title: detail, detail });
    }
    return (await res.json()) as MessagingDocUploadPreview;
  },
};

export const audiencesApi = {
  /** Undo a deactivate — see smesApi.restore for why this exists. */
  restore: (a: AudienceProfileRead, actor_label = "system") =>
    request<AudienceProfileRead>(`${BASE}/audience-profiles/${a.id}`, {
      method: "PUT",
      query: { actor_label },
      body: { ...a, is_active: true },
    }),
  list: (params: ListParams = {}) =>
    request<Page<AudienceProfileRead>>(`${BASE}/audience-profiles`, { query: params }),
  get: (id: string) => request<AudienceProfileRead>(`${BASE}/audience-profiles/${id}`),
  create: (body: AudienceProfileCreate, actor_label = "system") =>
    request<AudienceProfileRead>(`${BASE}/audience-profiles`, {
      method: "POST",
      body,
      query: { actor_label },
    }),
  update: (id: string, body: AudienceProfileUpdate, actor_label = "system") =>
    request<AudienceProfileRead>(`${BASE}/audience-profiles/${id}`, {
      method: "PUT",
      body,
      query: { actor_label },
    }),
  deactivate: (id: string, actor_label = "system") =>
    request<void>(`${BASE}/audience-profiles/${id}`, {
      method: "DELETE",
      query: { actor_label },
    }),
};

type SmeListParams = ListParams & {
  team?: string;
  /** True = everyone off the primary team; false = on it. */
  external_only?: boolean;
  /** Omit to include deactivated SMEs; true for active only. */
  is_active?: boolean;
};

export const smesApi = {
  /**
   * Undo a deactivate.
   *
   * DELETE on these resources is a SOFT delete — the row stays and goes
   * inactive. The list kept showing it while hiding every action, so a row
   * could be deactivated once and then never removed or brought back. There
   * is no dedicated reactivate endpoint; PUT already accepts is_active, so
   * this replays the row with the flag flipped.
   */
  restore: (sme: SmeRead, actor_label = "system") =>
    request<SmeRead>(`${BASE}/smes/${sme.id}`, {
      method: "PUT",
      query: { actor_label },
      body: {
        full_name: sme.full_name,
        email: sme.email,
        team: sme.team,
        audience_focus: sme.audience_focus,
        location_country: sme.location_country,
        location_city: sme.location_city,
        bio: sme.bio,
        languages: sme.languages,
        external_links: sme.external_links ?? {},
        pillar_ids: sme.pillar_ids ?? [],
        is_active: true,
      },
    }),
  list: (params: SmeListParams = {}) =>
    request<Page<SmeRead>>(`${BASE}/smes`, { query: params }),
  get: (id: string) => request<SmeRead>(`${BASE}/smes/${id}`),
  analytics: (id: string) => request<SmeAnalytics>(`${BASE}/smes/${id}/analytics`),
  create: (body: SmeCreate, actor_label = "system") =>
    request<SmeRead>(`${BASE}/smes`, { method: "POST", body, query: { actor_label } }),
  update: (id: string, body: SmeUpdate, actor_label = "system") =>
    request<SmeRead>(`${BASE}/smes/${id}`, {
      method: "PUT",
      body,
      query: { actor_label },
    }),
  deactivate: (id: string, actor_label = "system") =>
    request<void>(`${BASE}/smes/${id}`, { method: "DELETE", query: { actor_label } }),
};

// ---------------------------------------------------------------------------
// Conferences (plan 20 review UI)
// ---------------------------------------------------------------------------
type ConferenceListParams = {
  page?: number;
  per_page?: number;
  status?: string | string[];
  sort?: "score" | "fit" | "speakers" | "date" | "name" | "cfp_close";
  /** Secondary sort — breaks ties the primary leaves (e.g. cfp_close + fit). */
  then_by?: "score" | "fit" | "speakers" | "date" | "name" | "cfp_close";
  // Slice filters. These are predicates over the ranked list, so a
  // filtered view keeps each conference's GLOBAL rank — the top row of
  // a country filter is still "#7 overall", never a fresh "#1".
  country?: string[];
  city?: string;
  starts_after?: string;
  starts_before?: string;
  cfp_open?: boolean;
  /** Only CFPs closing between today and N days out. Unknown deadlines drop. */
  cfp_closes_within_days?: number;
  max_cost_usd?: number;
  include_virtual?: boolean;
  attendance_filter?: "all" | "new" | "returning";
  /** Our own involvement, as opposed to the event's own history. */
  engagement?: "all" | "going" | "attended" | "none";
  /** False (default) hides already-closed CFPs unless we have a stake. */
  include_closed_cfp?: boolean;
};

export const conferencesApi = {
  list: (params: ConferenceListParams = {}) =>
    request<ConferenceListResponse>(`${BASE}/conferences`, { query: params }),
  get: (id: string) =>
    request<import("@/lib/api-types").ConferenceRead>(`${BASE}/conferences/${id}`),
  create: (body: ConferenceCreate) =>
    request<ConferenceCreateResponse>(`${BASE}/conferences`, {
      method: "POST",
      body,
    }),
  delete: (id: string, actor_label = "user_delete") =>
    request<void>(`${BASE}/conferences/${id}`, {
      method: "DELETE",
      query: { actor_label },
    }),
  match: (id: string) => request<ConferenceMatchResponse>(`${BASE}/conferences/${id}/match`),
  sources: (id: string) =>
    request<ConferenceSourcesResponse>(`${BASE}/conferences/${id}/sources`),
  smes: (id: string, k = 5) =>
    request<ConferenceSmesResponse>(`${BASE}/conferences/${id}/smes`, { query: { k } }),
  importFormat: () =>
    request<import("@/lib/api-types").ImportColumnSpec[]>(
      `${BASE}/conferences/import/format`,
    ),
  importPast: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<import("@/lib/api-types").ImportResult>(`${BASE}/conferences/import`, {
      method: "POST",
      form: fd,
    });
  },
  talks: (id: string, k = 10) =>
    request<ConferenceTalksResponse>(`${BASE}/conferences/${id}/talks`, { query: { k } }),
  decisions: (id: string) =>
    request<DecisionListResponse>(`${BASE}/conferences/${id}/decisions`),
  createDecision: (id: string, body: DecisionCreate) =>
    request<DecisionRead>(`${BASE}/conferences/${id}/decisions`, {
      method: "POST",
      body,
    }),
  dashboardStats: () => request<DashboardStats>(`${BASE}/conferences/stats/dashboard`),
  statsByLocation: () =>
    request<{
      items: Array<{
        id: string;
        name: string;
        city: string | null;
        country: string | null;
        lat: number;
        lng: number;
        status: string;
        start_date: string | null;
      }>;
    }>(`${BASE}/conferences/stats/by-location`),
  brief: (id: string, team_size = 1, force = false) =>
    request<ConferenceBrief>(`${BASE}/conferences/${id}/brief`, {
      query: { team_size, force },
    }),
};

// ---------------------------------------------------------------------------
export const notificationsApi = {
  list: (params: { kind?: string; include_seen?: boolean; limit?: number } = {}) =>
    request<NotificationsList>(`${BASE}/notifications`, { query: params }),
  unreadCount: (kind?: string) =>
    request<{ count: number; kind: string | null }>(
      `${BASE}/notifications/unread-count`,
      { query: kind ? { kind } : {} },
    ),
  latest: (kind: string, unread_only = false) =>
    request<NotificationRead>(`${BASE}/notifications/latest`, {
      query: { kind, unread_only },
    }),
  dismiss: (id: string) =>
    request<{ id: string; seen: boolean }>(
      `${BASE}/notifications/${id}/dismiss`,
      { method: "POST" },
    ),
  cfpDigestMarkdown: () =>
    request<CfpDigestMarkdown>(`${BASE}/notifications/cfp-digest/markdown`),
};

// ---------------------------------------------------------------------------
// Agent chat (plan 22)
// ---------------------------------------------------------------------------
export const agentApi = {
  listSessions: (params: { include_archived?: boolean; limit?: number } = {}) =>
    request<{ sessions: AgentSession[] }>(`${BASE}/agent/sessions`, {
      query: params,
    }),
  createSession: (title?: string) =>
    request<AgentSession>(`${BASE}/agent/sessions`, {
      method: "POST",
      body: { title: title ?? null },
    }),
  getSession: (id: string) =>
    request<AgentSession>(`${BASE}/agent/sessions/${id}`),
  updateSession: (
    id: string,
    body: { title?: string | null; archived?: boolean },
  ) =>
    request<AgentSession>(`${BASE}/agent/sessions/${id}`, {
      method: "PATCH",
      body,
    }),
  archiveSession: (id: string) =>
    request<{ id: string; archived: boolean }>(`${BASE}/agent/sessions/${id}`, {
      method: "DELETE",
    }),
  listMessages: (id: string) =>
    request<{ session_id: string; messages: AgentMessage[] }>(
      `${BASE}/agent/sessions/${id}/messages`,
    ),
  ask: (id: string, content: string, k = 6) =>
    request<AgentReply>(`${BASE}/agent/sessions/${id}/messages`, {
      method: "POST",
      body: { content, k },
    }),
};

// ---------------------------------------------------------------------------
// Diagnostics (plan 26)
// ---------------------------------------------------------------------------
/**
 * Operator settings.
 *
 * Three pages hit /admin/settings with raw `fetch`, which skips everything
 * `request` does: the ApiError shape, the RFC 7807 problem body, and the
 * credentials/headers policy. Routed through the client like every other
 * resource.
 */
/** Matcher freshness + bulk rescore. */
export type MatcherFreshness = {
  corpus_changed_at: string | null;
  total_scored: number;
  stale_count: number;
  running: boolean;
  progress: { done: number; total: number } | null;
};

export const matcherApi = {
  freshness: () => request<MatcherFreshness>(`${BASE}/admin/matcher/freshness`),
  recomputeAll: () =>
    request<{ queued_job_id: string }>(`${BASE}/admin/matcher/recompute-all`, {
      method: "POST",
    }),
};

export const settingsApi = {
  list: () => request<SettingsResponse>(`${BASE}/admin/settings`),
  update: (values: Record<string, unknown>, actor_label = "ui") =>
    request<SettingsResponse>(`${BASE}/admin/settings`, {
      method: "PATCH",
      body: { ...values, actor_label },
    }),
  reset: (name: string) =>
    request<void>(`${BASE}/admin/settings/${name}`, { method: "DELETE" }),
};

/**
 * The operator's event-kind vocabulary.
 *
 * Deliberately read from settings rather than hardcoded: the kinds are
 * operator-owned, and a literal list in the SPA would silently disagree
 * with the one the extractor and the filters actually use.
 */
export async function fetchEventKinds(): Promise<string[]> {
  const res = await settingsApi.list();
  const row = res.items?.find((i) => i.spec?.name === "event_kinds");
  const value = row?.value;
  return Array.isArray(value) ? (value as string[]) : [];
}

export const analyticsApi = {
  overview: (
    params: {
      pillar_id?: string;
      country?: string;
      months?: number;
      status?: string[];
      event_kind?: string[];
      include_virtual?: boolean;
      starts_after?: string;
      starts_before?: string;
    } = {},
  ) => request<AnalyticsOverview>(`${BASE}/analytics/overview`, { query: params }),
};

export const diagnosticsApi = {
  get: () => request<DiagnosticsResponse>(`${BASE}/diagnostics`),
  refresh: () =>
    request<void>(`${BASE}/diagnostics/refresh`, { method: "POST" }),
  retryJob: (job_id: string) =>
    request<DiagnosticsRetryResponse>(
      `${BASE}/diagnostics/jobs/${job_id}/retry`,
      { method: "POST" },
    ),
  clearLlmErrors: () =>
    request<{ cleared_at: string }>(`${BASE}/diagnostics/llm-errors/clear`, {
      method: "POST",
    }),
};

// ---------------------------------------------------------------------------
// Discovery (plan 35) — autonomous conference finder
// ---------------------------------------------------------------------------
export type DiscoveryHitOutcome = {
  url: string;
  title: string;
  crawl_ok: boolean;
  parse_status: string | null;
  conference_id: string | null;
  error: string | null;
};

export type DiscoveryResult = {
  prompt: string;
  provider: string;
  requested: number;
  search_hits: number;
  crawled: number;
  new_conferences: number;
  updated_conferences: number;
  parse_failures: number;
  outcomes: DiscoveryHitOutcome[];
  search_error: string | null;
  started_at: string;
  finished_at: string;
};

// ---------------------------------------------------------------------------
// Participation — who is going, when, and what they are doing there
// ---------------------------------------------------------------------------
export interface Participation {
  id: string;
  conference_id: string;
  sme_id: string | null;
  person_label: string;
  activity: "talk" | "booth" | "attend" | "sponsor";
  talk_id: string | null;
  arrives_on: string | null;
  departs_on: string | null;
  attended_at: string | null;
  /** Derived: attended_at is set, or departs_on has passed. */
  has_attended: boolean;
  notes: string;
}

export interface AttendanceSummary {
  edition_year: number | null;
  spend_usd: number | null;
  leads_generated: number | null;
  audience_size_estimate: number | null;
  attendance_verdict: "would_attend" | "unsure" | "would_not_attend" | null;
  attendance_notes: string;
}

export type ParticipationInput = {
  person_label?: string;
  sme_id?: string | null;
  activity: Participation["activity"];
  arrives_on?: string | null;
  departs_on?: string | null;
  notes?: string;
};

export const participationApi = {
  list: (conferenceId: string) =>
    request<Participation[]>(`${BASE}/conferences/${conferenceId}/participation`),
  add: (conferenceId: string, body: ParticipationInput) =>
    request<Participation>(`${BASE}/conferences/${conferenceId}/participation`, {
      method: "POST",
      body,
    }),
  update: (id: string, body: ParticipationInput) =>
    request<Participation>(`${BASE}/participation/${id}`, { method: "PATCH", body }),
  remove: (id: string) =>
    request<void>(`${BASE}/participation/${id}`, { method: "DELETE" }),
  /** Confirm, or take back, that this person actually went. */
  markAttended: (id: string, attended: boolean) =>
    request<Participation>(`${BASE}/participation/${id}/attended`, {
      method: "POST",
      body: { attended },
    }),
  getAttendance: (conferenceId: string) =>
    request<AttendanceSummary>(`${BASE}/conferences/${conferenceId}/attendance`),
  setAttendance: (conferenceId: string, body: AttendanceSummary) =>
    request<AttendanceSummary>(`${BASE}/conferences/${conferenceId}/attendance`, {
      method: "PUT",
      body,
    }),
};

export const discoveryApi = {
  /**
   * Pull the developers.events feed.
   *
   * `only_ai` is deliberately NOT passed. It defaults to false server-side
   * because, measured against the live feed, that filter dropped 375 of
   * 801 future events — including KeyCloakCon, ArgoCon and Open Source
   * Summit Korea. This call used to pass `only_ai: true` explicitly,
   * which kept the filter on regardless of the default.
   */
  ingestFeed: () =>
    request<{
      new_conferences: number;
      updated_conferences: number;
      total_in_feed: number;
      matched_filter: number;
      /** Future events the keyword filter rejected, when it is enabled. */
      dropped_by_keyword_filter: number;
    }>(
      `${BASE}/admin/discovery/ingest-feed`,
      { method: "POST", body: { future_only: true } },
    ),
};

// ---------------------------------------------------------------------------
// Pillars (v2)
// ---------------------------------------------------------------------------
export const pillarsApi = {
  list: () => request<PillarRead[]>(`${BASE}/pillars`),
  get: (id: string) => request<PillarRead>(`${BASE}/pillars/${id}`),
  create: (body: PillarCreate) =>
    request<PillarRead>(`${BASE}/pillars`, { method: "POST", body }),
  update: (id: string, body: PillarUpdate) =>
    request<PillarRead>(`${BASE}/pillars/${id}`, { method: "PUT", body }),
  delete: (id: string) =>
    request<void>(`${BASE}/pillars/${id}`, { method: "DELETE" }),

  listSmes: (id: string) =>
    request<SmePillarRead[]>(`${BASE}/pillars/${id}/smes`),
  linkSme: (id: string, smeId: string, body: SmePillarLink) =>
    request<SmePillarRead>(`${BASE}/pillars/${id}/smes/${smeId}`, { method: "POST", body }),
  unlinkSme: (id: string, smeId: string) =>
    request<void>(`${BASE}/pillars/${id}/smes/${smeId}`, { method: "DELETE" }),

  analytics: (id: string) => request<PillarAnalytics>(`${BASE}/pillars/${id}/analytics`),
  listConferences: (id: string) =>
    request<PillarConferenceItem[]>(`${BASE}/pillars/${id}/conferences`),
  listTalks: (id: string) =>
    request<PillarTalkItem[]>(`${BASE}/pillars/${id}/talks`),
  listAudiences: (id: string) =>
    request<PillarAudienceItem[]>(`${BASE}/pillars/${id}/audiences`),

};

// ---------------------------------------------------------------------------
// Talks (v2)
// ---------------------------------------------------------------------------
export const talksApi = {
  list: (params: {
    page?: number;
    per_page?: number;
    pillar_id?: string;
    sme_id?: string;
    review_status?: string;
    is_active?: boolean;
  } = {}) => {
    const sp = new URLSearchParams();
    if (params.page) sp.set("page", String(params.page));
    if (params.per_page) sp.set("per_page", String(params.per_page));
    if (params.pillar_id) sp.set("pillar_id", params.pillar_id);
    if (params.sme_id) sp.set("sme_id", params.sme_id);
    if (params.review_status) sp.set("review_status", params.review_status);
    if (params.is_active !== undefined) sp.set("is_active", String(params.is_active));
    const qs = sp.toString();
    return request<import("@/lib/api-types").Page<TalkRead>>(
      `${BASE}/talks${qs ? `?${qs}` : ""}`,
    );
  },
  get: (id: string) => request<TalkRead>(`${BASE}/talks/${id}`),
  create: (body: TalkCreate) =>
    request<TalkRead>(`${BASE}/talks`, { method: "POST", body }),
  update: (id: string, body: TalkUpdate) =>
    request<TalkRead>(`${BASE}/talks/${id}`, { method: "PUT", body }),
  delete: (id: string) =>
    request<void>(`${BASE}/talks/${id}`, { method: "DELETE" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<TalkUploadPreview>(`${BASE}/talks/upload`, { method: "POST", form });
  },
  submit: (talkId: string, body: TalkSubmissionCreate) =>
    request<TalkSubmissionRead>(`${BASE}/talks/${talkId}/submit`, {
      method: "POST",
      body,
    }),
  reuseCheck: (id: string) =>
    request<ReuseCheckResult>(`${BASE}/talks/${id}/reuse-check`),
};

// ---------------------------------------------------------------------------
// Talk tags (v2)
// ---------------------------------------------------------------------------
