/**
 * /conferences/{id} — detail page (plan 20).
 *
 * Panels:
 *   - Header: name + dates + location + website + status pill
 *   - Score panel: overall + per-stage bars + rationale
 *   - SME panel: top-K with per-dimension bars
 *   - Sources panel: contributing raw_pages (plan 14)
 *   - Decision panel: Approve / Reject / Needs Review + reason + history
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { useMe } from "@/hooks/useMe";

import { StatusPill } from "@/components/conferences/StatusPill";
import { AttendancePanel } from "@/components/conferences/AttendancePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, conferencesApi } from "@/lib/api";
import type {
  ConferenceRead,
  DecisionVerdict,
  SmeBreakdown,
} from "@/lib/api-types";

export const Route = createFileRoute("/conferences_/$id")({
  component: ConferenceDetailPage,
});

function ConferenceDetailPage() {
  const { id } = Route.useParams();
  const conferenceQ = useQuery({
    queryKey: ["conferences", id],
    queryFn: () => conferencesApi.get(id),
  });
  const matchQ = useQuery({
    queryKey: ["conferences", id, "match"],
    queryFn: () => conferencesApi.match(id),
  });
  const smesQ = useQuery({
    queryKey: ["conferences", id, "smes"],
    queryFn: () => conferencesApi.smes(id, 5),
  });
  const talksQ = useQuery({
    queryKey: ["conferences", id, "talks"],
    queryFn: () => conferencesApi.talks(id, 10),
  });
  const sourcesQ = useQuery({
    queryKey: ["conferences", id, "sources"],
    queryFn: () => conferencesApi.sources(id),
  });
  const decisionsQ = useQuery({
    queryKey: ["conferences", id, "decisions"],
    queryFn: () => conferencesApi.decisions(id),
  });

  if (conferenceQ.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-60 w-full" />
      </div>
    );
  }
  if (conferenceQ.error || !conferenceQ.data) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-danger">
          Could not load this conference.
        </CardContent>
      </Card>
    );
  }

  const conference = conferenceQ.data;
  const match = matchQ.data?.match ?? null;
  const sources = sourcesQ.data?.sources ?? [];
  const decisions = decisionsQ.data?.decisions ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <Link to="/conferences" className="text-xs text-fg-muted hover:text-fg">
          ← All conferences
        </Link>
      </div>

      <ConferenceHeader conference={conference} />

      <ScorePanel
        match={match}
        loading={matchQ.isLoading}
      />

      <SmesPanel loading={smesQ.isLoading} data={smesQ.data} />

      <TalksPanel loading={talksQ.isLoading} data={talksQ.data} />

      {/* Who is going, and how it went. Until this existed the app could
          SHOW "previously attended" in three places and set it in none. */}
      <AttendancePanel conferenceId={id} />

      <SourcesPanel sources={sources} loading={sourcesQ.isLoading} />

      <DecisionPanel
        conferenceId={id}
        currentStatus={conference.status}
        history={decisions}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------
function ConferenceHeader({ conference }: { conference: ConferenceRead }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{conference.name}</h1>
        <StatusPill status={conference.status} />
        {conference.is_virtual ? <Badge variant="muted">Virtual</Badge> : null}
        <Link
          to="/conferences/$id/brief"
          params={{ id: conference.id }}
          target="_blank"
          rel="noreferrer noopener"
          className="ml-auto text-xs text-accent underline-offset-2 hover:underline"
        >
          Open brief →
        </Link>
      </div>
      <p className="text-sm text-fg-muted">
        {conference.start_date ?? "Dates TBD"}
        {conference.end_date && conference.end_date !== conference.start_date
          ? ` – ${conference.end_date}`
          : ""}
        {conference.location_city || conference.location_country
          ? ` · ${[conference.location_city, conference.location_country]
              .filter(Boolean)
              .join(", ")}`
          : ""}
      </p>
      {/* External-link row: homepage + apply-here button + CFP close */}
      <div className="flex flex-wrap items-center gap-3">
        {conference.website ? (
          <a
            href={conference.website}
            target="_blank"
            rel="noreferrer noopener"
            className="text-sm text-accent underline-offset-2 hover:underline"
          >
            {conference.website}
          </a>
        ) : null}
        {conference.cfp_url ? (
          <a
            href={conference.cfp_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 rounded bg-accent px-3 py-1 text-sm font-medium text-accent-fg hover:bg-accent-hover"
          >
            Apply / view CFP ↗
          </a>
        ) : null}
        {conference.cfp_close_at ? (
          <span className="text-xs text-fg-muted">
            CFP closes <strong className="text-fg">{conference.cfp_close_at}</strong>
          </span>
        ) : null}
      </div>
      {conference.cfp_topics_of_interest && conference.cfp_topics_of_interest.length > 0 ? (
        <div className="mt-1">
          <p className="text-xs uppercase tracking-wider text-fg-muted">CFP topics of interest</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {conference.cfp_topics_of_interest.map((t) => (
              <Badge key={t} variant="muted">
                {t}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
      {conference.topics && conference.topics.length > 0 ? (
        <div className="mt-1">
          <p className="text-xs uppercase tracking-wider text-fg-muted">Topics</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {conference.topics.map((t) => (
              <Badge key={t} variant="muted">
                {t}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Score panel
// ---------------------------------------------------------------------------
function ScorePanel({
  match,
  loading,
}: {
  match: import("@/lib/api-types").ConferenceMatch | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card>
        <CardContent className="py-6">
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (!match) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Match score</CardTitle>
        </CardHeader>
        <CardContent className="py-4 text-sm text-fg-muted">
          Matcher couldn't produce a score — usually means there are no
          active messaging documents or SMEs to compare against. Add one
          on /messaging or /smes and reopen this page.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="flex flex-row items-baseline justify-between">
        <CardTitle>Match score</CardTitle>
        <div className="flex items-baseline gap-1 tabular-nums">
          <span className="text-3xl font-semibold">
            {Math.round(match.overall_score * 100)}
          </span>
          <span className="text-xs text-fg-muted">/ 100</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ScoreRow label="Fit — do they care about what we do" value={match.fit_score} />
        <ScoreRow label="Speakers — can we show up well" value={match.speaker_score} />

        {/* A boost breakdown used to render here: signed
            percentage-point adjustments for CFP urgency, series
            memory and a recency penalty. Nobody can act on
            "recency penalty: -4", and the facts underneath it (the
            CFP closes soon; we have been to this series before) are
            already on this page as a deadline and a badge. The
            boosts still apply to the score - they are no longer
            narrated. */}
        {match.judge_verdict === "veto" ? (
          <div className="mt-2 rounded-md border border-danger bg-surface-2 p-3 text-sm text-fg">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-danger">
              Vetoed — wrong audience
            </p>
            <p>{match.judge_reason}</p>
            <p className="mt-2 text-xs text-fg-muted">
              A veto is a review flag, not a deletion. If this looks wrong,
              the reason above is what to argue with.
            </p>
          </div>
        ) : null}
        {match.rationale_text ? (
          <div className="mt-2 rounded-md border border-border-subtle bg-surface-2 p-3 text-sm text-fg">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-fg-muted">
              Match rationale
            </p>
            <p>{match.rationale_text}</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ScoreRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-sm">{label}</span>
        <span className="text-sm font-medium tabular-nums">{Math.round(value * 100)}</span>
      </div>
      <Progress value={value} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// SME panel
// ---------------------------------------------------------------------------
function SmesPanel({
  loading,
  data,
}: {
  loading: boolean;
  data: import("@/lib/api-types").ConferenceSmesResponse | undefined;
}) {
  if (loading) {
    return (
      <Card>
        <CardContent className="py-6">
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }
  const ranked =
    (data?.above_gate?.length ?? 0) > 0
      ? (data?.above_gate ?? [])
      : (data?.near_misses ?? []);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Recommended SMEs</CardTitle>
          {data && (data.above_gate ?? []).length === 0 ? (
            <p className="mt-1 text-xs text-warning">
              No candidates above gate ({data.gate}); showing near-misses.
            </p>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {ranked.length === 0 ? (
          <p className="text-sm text-fg-muted">No SMEs scored for this conference yet.</p>
        ) : (
          ranked.map((b) => <SmeCard key={b.sme_id} b={b} />)
        )}
      </CardContent>
    </Card>
  );
}

function SmeCard({ b }: { b: SmeBreakdown }) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-2 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium">
            {b.full_name}{" "}
            <span className="text-xs font-normal text-fg-muted">
              · {b.team}
              {b.is_external ? " (external)" : ""}
            </span>
          </h3>
          <p className="text-xs text-fg-muted">
            {[b.location_city, b.location_country].filter(Boolean).join(", ") || "—"}
          </p>
        </div>
        <div className="flex flex-col items-end">
          <div className="flex items-baseline gap-1 tabular-nums">
            <span className="text-xl font-semibold">{Math.round(b.composite * 100)}</span>
            <span className="text-xs text-fg-muted">/ 100</span>
          </div>
          <span className="text-xs font-medium uppercase tracking-wider text-fg-muted">composite</span>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-4">
        <DimBar label="Audience" value={b.dimensions.audience_overlap} />
        <DimBar label="Bio" value={b.dimensions.bio_similarity} />
        <DimBar label="Location" value={b.dimensions.location} />
        <DimBar label="Past" value={b.dimensions.past_attendance} />
      </div>
    </div>
  );
}

// Deliberately its own ranking, separate from SMEs: a CFP committee accepts
// a talk first and a speaker second, so "which of our talks fits this event"
// and "who should go" are two independent lists. The similarity uses the
// same measure as the SME Bio bar above, so the numbers are comparable.
function TalksPanel({
  loading,
  data,
}: {
  loading: boolean;
  data: import("@/lib/api-types").ConferenceTalksResponse | undefined;
}) {
  if (loading) {
    return (
      <Card>
        <CardContent className="py-6">
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }
  const talks = data?.talks ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Talks to pitch</CardTitle>
        <p className="mt-1 text-xs text-fg-muted">
          Your talk library ranked against this conference. Same similarity
          measure as the Bio bar above.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {talks.length === 0 ? (
          <p className="text-sm text-fg-muted">
            No talks in the library yet. Add them on the{" "}
            <Link to="/talks" className="underline hover:text-fg">
              Talks page
            </Link>{" "}
            and they will be ranked here automatically.
          </p>
        ) : (
          talks.map((t) => (
            <div
              key={t.talk_id}
              className="rounded-md border border-border-subtle bg-surface-2 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-medium">{t.title}</h3>
                  <p className="text-xs text-fg-muted">
                    {[t.primary_sme_name, t.pillar_name].filter(Boolean).join(" · ") || "—"}
                  </p>
                  <div className="mt-1 flex gap-2">
                    {t.already_submitted ? (
                      <Badge variant="success">Already submitted here</Badge>
                    ) : null}
                    {!t.has_embedding ? (
                      <Badge variant="warning">
                        Not indexed — re-save the talk to score it
                      </Badge>
                    ) : null}
                  </div>
                </div>
                <div className="flex flex-col items-end">
                  <div className="flex items-baseline gap-1 tabular-nums">
                    <span className="text-xl font-semibold">
                      {Math.round(t.similarity * 100)}
                    </span>
                    <span className="text-xs text-fg-muted">/ 100</span>
                  </div>
                  <span className="text-xs font-medium uppercase tracking-wider text-fg-muted">
                    fit
                  </span>
                </div>
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

// null = the matcher couldn't measure this dimension (no tags on one side),
// dropped it, and renormalised the remaining weights — a different thing
// from a real 0, and it must not read as one.
function DimBar({ label, value }: { label: string; value: number | null | undefined }) {
  if (value == null) {
    return (
      <div title="Not measured — no tags on one side. Dropped from the composite; remaining weights renormalised.">
        <div className="mb-1 flex items-baseline justify-between text-xs">
          <span className="text-fg-muted">{label}</span>
          <span className="text-fg-subtle">n/a</span>
        </div>
        <Progress value={0} size="sm" className="opacity-30" />
      </div>
    );
  }
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-fg-muted">{label}</span>
        <span className="font-medium text-fg tabular-nums">{Math.round(value * 100)}</span>
      </div>
      <Progress value={value} size="sm" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sources panel
// ---------------------------------------------------------------------------
function SourcesPanel({
  sources,
  loading,
}: {
  sources: import("@/lib/api-types").ConferenceSourceRow[];
  loading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sources</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-16 w-full" />
        ) : sources.length === 0 ? (
          <p className="text-sm text-fg-muted">No contributing raw pages.</p>
        ) : (
          <ul className="space-y-2">
            {sources.map((s) => (
              <li
                key={s.raw_page_id}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="truncate text-accent underline-offset-2 hover:underline"
                >
                  {s.url}
                </a>
                <span className="shrink-0 text-xs text-fg-muted tabular-nums">
                  HTTP {s.http_status} · {s.fetched_at?.slice(0, 10) ?? "?"} ·{" "}
                  <code className="rounded bg-surface-3 px-1">{s.hash_prefix}</code>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Decision panel
// ---------------------------------------------------------------------------
function DecisionPanel({
  conferenceId,
  currentStatus,
  history,
}: {
  conferenceId: string;
  currentStatus: string;
  history: import("@/lib/api-types").DecisionRead[];
}) {
  const queryClient = useQueryClient();
  const { label: meLabel } = useMe();
  const [reason, setReason] = useState("");
  const [actor, setActor] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Pre-fill the actor field with the signed-in user once the identity
  // loads. `actor` is read through the setter callback rather than listed as
  // a dependency: depending on it would re-run this on every keystroke and
  // fight the user's own typing.
  useEffect(() => {
    if (meLabel) setActor((current) => current || meLabel);
  }, [meLabel]);

  const mut = useMutation({
    mutationFn: (verdict: DecisionVerdict) =>
      conferencesApi.createDecision(conferenceId, {
        decision: verdict,
        reason: reason.trim() || null,
        decided_by_label: actor.trim() || "anonymous",
      }),
    onSuccess: () => {
      setReason("");
      setSubmitError(null);
      queryClient.invalidateQueries({ queryKey: ["conferences", conferenceId] });
      queryClient.invalidateQueries({
        queryKey: ["conferences", conferenceId, "decisions"],
      });
      queryClient.invalidateQueries({ queryKey: ["conferences"] });
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError ? err.problem.detail ?? err.problem.title : String(err);
      setSubmitError(msg);
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Decision</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="actor">Your name / label (optional)</Label>
            <Input
              id="actor"
              placeholder="e.g. ian"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="reason">Reason (optional)</Label>
            <Input
              id="reason"
              placeholder="short note for the audit log"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={2000}
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="default"
            onClick={() => mut.mutate("approved")}
            disabled={mut.isPending || currentStatus === "approved"}
          >
            Approve
          </Button>
          <Button
            variant="outline"
            onClick={() => mut.mutate("needs_review")}
            disabled={mut.isPending}
          >
            Needs review
          </Button>
          <Button
            variant="danger"
            onClick={() => mut.mutate("rejected")}
            disabled={mut.isPending || currentStatus === "rejected"}
          >
            Reject
          </Button>
          <span className="ml-auto self-center text-xs text-fg-muted">
            Current status: <StatusPill status={currentStatus} />
          </span>
        </div>

        {submitError ? (
          <p className="rounded-md border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
            {submitError}
          </p>
        ) : null}

        {history.length > 0 ? (
          <div className="mt-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-muted">
              History
            </p>
            <ul className="space-y-1 text-xs text-fg-muted">
              {history.map((d) => (
                <li key={d.id}>
                  <span className="font-medium text-fg">{d.decision}</span> by{" "}
                  {d.decided_by_label} · {d.decided_at?.slice(0, 19).replace("T", " ")}
                  {d.reason ? ` — ${d.reason}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
