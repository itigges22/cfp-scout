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
  AgentMessage,
  AgentReply,
  AgentSession,
  ApiProblem,
  AudienceProfileCreate,
  AudienceProfileRead,
  AudienceProfileUpdate,
  ConferenceListResponse,
  ConferenceMatchResponse,
  ConferenceSmesResponse,
  ConferenceSourcesResponse,
  DashboardStats,
  DecisionCreate,
  DecisionListResponse,
  DecisionRead,
  CfpDigestMarkdown,
  GraphResponse,
  MessagingDocumentCreate,
  MessagingDocumentRead,
  MessagingDocumentUpdate,
  NotificationRead,
  NotificationsList,
  Page,
  PastConferenceCreate,
  PastConferenceImportResult,
  PastConferenceRead,
  PastConferenceUpdate,
  SmeCreate,
  SmeRead,
  SmeUpdate,
  TopicCreate,
  TopicRead,
  TopicUpdate,
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
};

export const messagingApi = {
  list: (params: ListParams = {}) =>
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
};

export const audiencesApi = {
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

type SmeListParams = ListParams & { team?: string };

export const smesApi = {
  list: (params: SmeListParams = {}) =>
    request<Page<SmeRead>>(`${BASE}/smes`, { query: params }),
  get: (id: string) => request<SmeRead>(`${BASE}/smes/${id}`),
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

type PastConferenceListParams = { page?: number; per_page?: number; q?: string; year?: number };

export const pastConferencesApi = {
  list: (params: PastConferenceListParams = {}) =>
    request<Page<PastConferenceRead>>(`${BASE}/past-conferences`, { query: params }),
  get: (id: string) => request<PastConferenceRead>(`${BASE}/past-conferences/${id}`),
  create: (body: PastConferenceCreate, actor_label = "system") =>
    request<PastConferenceRead>(`${BASE}/past-conferences`, {
      method: "POST",
      body,
      query: { actor_label },
    }),
  update: (id: string, body: PastConferenceUpdate, actor_label = "system") =>
    request<PastConferenceRead>(`${BASE}/past-conferences/${id}`, {
      method: "PUT",
      body,
      query: { actor_label },
    }),
  importCsv: (file: File, ignore_errors = false, actor_label = "csv_import") => {
    const form = new FormData();
    form.append("file", file);
    return request<PastConferenceImportResult>(`${BASE}/past-conferences/import`, {
      method: "POST",
      form,
      query: { ignore_errors, actor_label },
    });
  },
};

type TopicListParams = { page?: number; per_page?: number; q?: string; pending_only?: boolean | null };

export const topicsApi = {
  list: (params: TopicListParams = {}) =>
    request<Page<TopicRead>>(`${BASE}/topics`, { query: params }),
  get: (id: string) => request<TopicRead>(`${BASE}/topics/${id}`),
  create: (body: TopicCreate, actor_label = "system") =>
    request<TopicRead>(`${BASE}/topics`, { method: "POST", body, query: { actor_label } }),
  update: (id: string, body: TopicUpdate, actor_label = "system") =>
    request<TopicRead>(`${BASE}/topics/${id}`, {
      method: "PUT",
      body,
      query: { actor_label },
    }),
  approve: (id: string, actor_label = "system") =>
    request<TopicRead>(`${BASE}/topics/${id}/approve`, {
      method: "POST",
      query: { actor_label },
    }),
  reject: (id: string, actor_label = "system") =>
    request<void>(`${BASE}/topics/${id}/reject`, {
      method: "POST",
      query: { actor_label },
    }),
};

// ---------------------------------------------------------------------------
// Conferences (plan 20 review UI)
// ---------------------------------------------------------------------------
type ConferenceListParams = {
  page?: number;
  per_page?: number;
  status?: string | string[];
  sort?: "score" | "date" | "name";
};

export const conferencesApi = {
  list: (params: ConferenceListParams = {}) =>
    request<ConferenceListResponse>(`${BASE}/conferences`, { query: params }),
  get: (id: string) =>
    request<import("@/lib/api-types").ConferenceRead>(`${BASE}/conferences/${id}`),
  match: (id: string) => request<ConferenceMatchResponse>(`${BASE}/conferences/${id}/match`),
  sources: (id: string) =>
    request<ConferenceSourcesResponse>(`${BASE}/conferences/${id}/sources`),
  smes: (id: string, k = 5) =>
    request<ConferenceSmesResponse>(`${BASE}/conferences/${id}/smes`, { query: { k } }),
  decisions: (id: string) =>
    request<DecisionListResponse>(`${BASE}/conferences/${id}/decisions`),
  createDecision: (id: string, body: DecisionCreate) =>
    request<DecisionRead>(`${BASE}/conferences/${id}/decisions`, {
      method: "POST",
      body,
    }),
  dashboardStats: () => request<DashboardStats>(`${BASE}/conferences/stats/dashboard`),
};

// ---------------------------------------------------------------------------
// Knowledge graph (plan 21 explorer)
// ---------------------------------------------------------------------------
type GraphFullParams = {
  kinds?: string | string[];
  status?: string | string[];
  since?: string;
  max_nodes?: number;
};

export const graphApi = {
  full: (params: GraphFullParams = {}) =>
    request<GraphResponse>(`${BASE}/graph/full`, { query: params }),
  neighborhood: (node_id: string, depth = 2) =>
    request<GraphResponse>(`${BASE}/graph/neighborhood`, {
      query: { node_id, depth },
    }),
  invalidate: () =>
    request<void>(`${BASE}/graph/invalidate`, { method: "POST" }),
};

// ---------------------------------------------------------------------------
// Notifications (plan 24)
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
