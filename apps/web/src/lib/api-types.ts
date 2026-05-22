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
