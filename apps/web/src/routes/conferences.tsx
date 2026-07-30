/**
 * /conferences — ranked list (plan 20).
 *
 * Server-side filter by status, server-side sort by score|date|name.
 * Each row links to the detail page. Bulk actions + CSV export are
 * deferred to a future pass.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Check, Download, Sparkles, Trash2, X, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useMe } from "@/hooks/useMe";

import { ImportPastDialog } from "@/components/conferences/ImportPastDialog";
import { NewConferenceDialog } from "@/components/conferences/NewConferenceDialog";
import { StatusPill } from "@/components/conferences/StatusPill";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { MatcherFreshness } from "@/lib/api";
import { matcherApi, conferencesApi, discoveryApi } from "@/lib/api";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/conferences")({
  component: ConferencesPage,
});

/**
 * One filter, not two.
 *
 * Status and "our involvement" were separate dropdowns, and the split was
 * confusing because they are two halves of the SAME question — where is this
 * conference in our pipeline. Status carried the matcher's verdict AND the
 * human decision; involvement carried whether anyone was going. You had to
 * reason about both to answer "what should I look at next".
 *
 * They are one control now. Each option sets whichever underlying parameter
 * it needs — the API still has both, because a matcher outcome and a
 * participation record are genuinely different rows.
 */
type Stage = {
  value: string;
  label: string;
  group: "Pipeline" | "Filtered out";
  status?: string | null;
  engagement?: Engagement;
};

const STAGES: Stage[] = [
  { value: "all", label: "Everything open", group: "Pipeline" },
  { value: "undecided", label: "Not decided yet", group: "Pipeline", engagement: "none" },
  { value: "approved", label: "Approved", group: "Pipeline", status: "approved" },
  { value: "going", label: "We're going", group: "Pipeline", engagement: "going" },
  { value: "attended", label: "Attended", group: "Pipeline", engagement: "attended" },
  { value: "needs_review", label: "Needs review", group: "Filtered out", status: "needs_review" },
  {
    value: "needs_sme_review",
    label: "No speaker yet",
    group: "Filtered out",
    status: "needs_sme_review",
  },
  {
    value: "low_messaging_fit",
    label: "Low fit",
    group: "Filtered out",
    status: "low_messaging_fit",
  },
] as const;

type SortOpt = "score" | "fit" | "speakers" | "date" | "name" | "cfp_close";

/** Our own involvement — distinct from AttendanceFilter, which is about the
 *  event's own history rather than whether we are going. */
type Engagement = "all" | "going" | "attended" | "none";

// Sort buttons + labels. Order matters: leftmost is the default.
//
// "score" is overall_score, which since the two-signal rewrite is a
// blend of exactly two things: `fit` (do they care about what we do)
// and `speakers` (can we show up well). Sorting by either component
// separately is a real operator action, not decoration - the two
// disagree often, and "great audience, nobody to send" and "perfect
// speaker, wrong room" need different responses.
//
// This comment described the OLD three-signal model (messaging /
// pillar / sme) for several releases after those collapsed into `fit`.
// A stale comment about scoring is worse than none: it is the thing
// someone reads before changing the scoring.
const SORT_OPTS: { value: SortOpt; label: string }[] = [
  { value: "cfp_close", label: "CFP deadline" },
  { value: "score", label: "Overall" },
  { value: "fit", label: "Fit" },
  { value: "speakers", label: "Speakers" },
  { value: "date", label: "Date" },
  { value: "name", label: "Name" },
];

type AttendanceFilter = "all" | "new" | "returning";
const ATTENDANCE_OPTS: { value: AttendanceFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "new", label: "New only" },
  { value: "returning", label: "Previously attended" },
];


/**
 * Scores are frozen at compute time — uploading messaging docs or editing
 * SMEs changes what the matcher WOULD say, but nothing rescores by itself
 * and, before this banner, nothing said so. The operator loaded their real
 * corpus and stared at identical numbers wondering if anything happened.
 *
 * Amber: data changed since scoring — one click queues the rescore (a
 * tracked background job, not an inline request). Blue: live progress from
 * matches.computed_at, no extra bookkeeping. Auto-refreshes the list when
 * the run finishes so the new ranking appears without a reload.
 */
function RescoreBanner() {
  const qc = useQueryClient();
  const wasRunning = useRef(false);
  const fresh = useQuery({
    queryKey: ["matcher-freshness"],
    queryFn: matcherApi.freshness,
    refetchInterval: (q) =>
      (q.state.data as MatcherFreshness | undefined)?.running ? 4000 : 60_000,
  });
  const kick = useMutation({
    mutationFn: matcherApi.recomputeAll,
    onSuccess: () => void fresh.refetch(),
  });

  useEffect(() => {
    if (wasRunning.current && fresh.data && !fresh.data.running) {
      void qc.invalidateQueries({ queryKey: ["conferences"] });
      void qc.invalidateQueries({ queryKey: ["matcher-freshness"] });
    }
    wasRunning.current = fresh.data?.running ?? false;
  }, [fresh.data, qc]);

  const d = fresh.data;
  if (!d) return null;

  if (d.running) {
    const p = d.progress;
    const pct = p && p.total > 0 ? Math.round((p.done / p.total) * 100) : null;
    return (
      <div className="flex items-center gap-3 rounded-lg border border-accent/40 bg-accent/5 px-4 py-3 text-sm">
        <Loader2 className="size-4 shrink-0 animate-spin text-accent" />
        <span className="text-fg">
          Rescoring conferences against your latest data
          {p ? ` — ${p.done} of ${p.total} done` : ""}…
        </span>
        {pct !== null && (
          <div className="ml-auto h-2 w-40 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
    );
  }

  if (d.stale_count > 0) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 text-sm">
        <span className="text-fg">
          {d.stale_count === d.total_scored
            ? "All conference scores predate your latest messaging / pillar / SME changes."
            : `${d.stale_count} of ${d.total_scored} conference scores predate your latest data changes.`}{" "}
          <span className="text-fg-muted">Rescoring re-ranks everything against what you just added.</span>
        </span>
        <Button
          size="sm"
          className="ml-auto shrink-0"
          onClick={() => kick.mutate()}
          disabled={kick.isPending}
        >
          {kick.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
          Rescore all
        </Button>
      </div>
    );
  }
  return null;
}

function ConferencesPage() {
  const [stage, setStage] = useState<string>("all");
  const [sort, setSort] = useState<SortOpt>("score");
  // Secondary sort. "" = none. Matters most behind a date key: deadlines
  // tie by the day, so "CFP close, then fit" is "soonest first, best fit
  // within each day" — the mix-and-match the single select couldn't say.
  const [thenBy, setThenBy] = useState<"" | SortOpt>("");
  const [attendanceFilter, setAttendanceFilter] = useState<AttendanceFilter>("all");
  // Our own involvement, plus the location and deadline controls. These were
  // all supported by the API and none of them were reachable from the UI.
  const [country, setCountry] = useState("");
  const [city, setCity] = useState("");
  const [includeClosedCfp, setIncludeClosedCfp] = useState(false);
  // "" = any deadline; otherwise days until CFP close. Combines with every
  // other control — the whole bar ANDs together, so "closes within 30 days,
  // sorted by fit, in the US" is one query.
  const [cfpWindow, setCfpWindow] = useState("");
  const [startsAfter, setStartsAfter] = useState("");
  const [startsBefore, setStartsBefore] = useState("");
  // Falls back to "Everything open" if a stale value ever survives in state.
  const activeStage = STAGES.find((x) => x.value === stage);
  const status = activeStage?.status ?? null;
  const engagement: Engagement = activeStage?.engagement ?? "all";
  const [showNewDialog, setShowNewDialog] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [discoverResult, setDiscoverResult] = useState<{
    new_conferences: number;
    updated_conferences: number;
    total_in_feed: number;
    matched_filter: number;
  } | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // Mirrors the list query's params exactly — export IS the current view.
  // A plain navigation, not fetch: Content-Disposition makes the browser
  // download the file without touching React state.
  const exportView = (format: "xlsx" | "csv") => {
    const p = new URLSearchParams();
    p.set("format", format);
    p.set("sort", sort);
    if (thenBy) p.set("then_by", thenBy);
    p.set("attendance_filter", attendanceFilter);
    p.set("engagement", engagement);
    p.set("include_closed_cfp", String(includeClosedCfp));
    if (country.trim()) p.append("country", country.trim().toUpperCase());
    if (city.trim()) p.set("city", city.trim());
    if (cfpWindow) p.set("cfp_closes_within_days", cfpWindow);
    if (startsAfter) p.set("starts_after", startsAfter);
    if (startsBefore) p.set("starts_before", startsBefore);
    const statuses = Array.isArray(status) ? status : status ? [status] : [];
    statuses.forEach((s) => p.append("status", s));
    window.location.assign(`/api/v1/conferences/export?${p.toString()}`);
  };

  const discoverMut = useMutation({
    mutationFn: async () => {
      return discoveryApi.ingestFeed();
    },
    onSuccess: (data) => {
      setDiscoverResult(data);
      queryClient.invalidateQueries({ queryKey: ["conferences"] });
    },
  });

  const queryKey = useMemo(
    () =>
      [
        "conferences",
        {
          stage,
          sort,
          thenBy,
          attendanceFilter,
          country,
          city,
          includeClosedCfp,
          cfpWindow,
          startsAfter,
          startsBefore,
        },
      ] as const,
    [
      stage,
      sort,
      thenBy,
      attendanceFilter,
      country,
      city,
      includeClosedCfp,
      cfpWindow,
      startsAfter,
      startsBefore,
    ],
  );
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () =>
      conferencesApi.list({
        sort,
        ...(thenBy ? { then_by: thenBy } : {}),
        attendance_filter: attendanceFilter,
        engagement,
        include_closed_cfp: includeClosedCfp,
        ...(country.trim() ? { country: [country.trim().toUpperCase()] } : {}),
        ...(city.trim() ? { city: city.trim() } : {}),
        ...(cfpWindow ? { cfp_closes_within_days: Number(cfpWindow) } : {}),
        ...(startsAfter ? { starts_after: startsAfter } : {}),
        ...(startsBefore ? { starts_before: startsBefore } : {}),
        ...(status ? { status } : {}),
        per_page: 100,
      }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Conferences"
        description="Ranked by matcher score · drill into a row for SMEs, rationale, decision actions."
      />

      <RescoreBanner />

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => setShowNewDialog(true)}>+ New conference</Button>
        <Button variant="outline" onClick={() => setShowImport(true)}>
          Import past…
        </Button>
        <Button
          variant="outline"
          onClick={() => discoverMut.mutate()}
          disabled={discoverMut.isPending}
        >
          <Sparkles className="mr-1.5 h-4 w-4" />
          {discoverMut.isPending ? "Discovering…" : "Discover more"}
        </Button>
      </div>

      {/* Filter bar. This was two rows of toggle buttons covering status,
          sort and past-attendance only — while the API already supported
          location, CFP state and our own involvement, none of which were
          reachable. Labelled controls rather than a pill wall: with this
          many axes a row of bubbles stops being scannable, and there is no
          room left to show which ones are active. */}
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3 rounded-lg border border-border bg-surface p-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Stage</span>
            <select
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              value={stage}
              onChange={(e) => setStage(e.currentTarget.value)}
            >
              {(["Pipeline", "Filtered out"] as const).map((g) => (
                <optgroup key={g} label={g}>
                  {STAGES.filter((x) => x.group === g).map((x) => (
                    <option key={x.value} value={x.value}>
                      {x.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Sort by</span>
            <select
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              value={sort}
              onChange={(e) => {
                const next = e.currentTarget.value as SortOpt;
                setSort(next);
                // A key can't tie-break itself.
                if (thenBy === next) setThenBy("");
              }}
            >
              {SORT_OPTS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Then by</span>
            <select
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              value={thenBy}
              onChange={(e) => setThenBy(e.currentTarget.value as "" | SortOpt)}
            >
              <option value="">—</option>
              {SORT_OPTS.filter((o) => o.value !== sort).map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Been before?</span>
            <select
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              value={attendanceFilter}
              onChange={(e) =>
                setAttendanceFilter(e.currentTarget.value as AttendanceFilter)
              }
            >
              {ATTENDANCE_OPTS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">CFP closes within</span>
            <select
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              value={cfpWindow}
              onChange={(e) => setCfpWindow(e.currentTarget.value)}
            >
              <option value="">Any deadline</option>
              <option value="7">7 days</option>
              <option value="14">14 days</option>
              <option value="30">30 days</option>
              <option value="60">60 days</option>
              <option value="90">90 days</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Starts after</span>
            <input
              type="date"
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              value={startsAfter}
              onChange={(e) => setStartsAfter(e.currentTarget.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Starts before</span>
            <input
              type="date"
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              value={startsBefore}
              onChange={(e) => setStartsBefore(e.currentTarget.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">Country</span>
            <input
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg w-20"
              placeholder="US"
              maxLength={2}
              value={country}
              onChange={(e) => setCountry(e.currentTarget.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-fg-muted">City</span>
            <input
              className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg w-36"
              placeholder="Berlin"
              value={city}
              onChange={(e) => setCity(e.currentTarget.value)}
            />
          </label>

          <label className="flex items-center gap-2 pb-1">
            <input
              type="checkbox"
              checked={includeClosedCfp}
              onChange={(e) => setIncludeClosedCfp(e.currentTarget.checked)}
            />
            <span className="text-xs text-fg-muted">
              Show closed CFPs{" "}
              <span className="text-fg-subtle">(hidden unless we&rsquo;re going)</span>
            </span>
          </label>

          <div className="ml-auto flex items-end gap-2">
            {(country ||
              city ||
              stage !== "all" ||
              includeClosedCfp ||
              cfpWindow ||
              startsAfter ||
              startsBefore) && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setCountry("");
                  setCity("");
                  setStage("all");
                  setIncludeClosedCfp(false);
                  setCfpWindow("");
                  setStartsAfter("");
                  setStartsBefore("");
                }}
              >
                Clear filters
              </Button>
            )}
            {/* Exports respect every active filter — the file is THIS view,
                not the whole corpus. Columns nobody has filled in yet
                (spend, leads, worth-it) ship anyway: the empty columns are
                the tracking checklist. */}
            <Button size="sm" variant="outline" onClick={() => exportView("xlsx")}>
              <Download className="mr-1.5 h-4 w-4" />
              Export view
            </Button>
            <Button size="sm" variant="outline" onClick={() => exportView("csv")}>
              CSV
            </Button>
          </div>
      </div>

      {discoverResult ? (
        <Card className="border-success/40 bg-success/5">
          <CardContent className="flex items-center justify-between gap-3 py-3">
            <p className="text-sm text-fg">
              Discovery pulled from <strong>{discoverResult.total_in_feed}</strong>{" "}
              upstream events; <strong>{discoverResult.matched_filter}</strong> matched
              AI/future filters; <strong>{discoverResult.new_conferences}</strong>{" "}
              new + {discoverResult.updated_conferences} updated. Matcher will run
              automatically; refresh in a minute to see scores settle.
            </p>
            <button
              type="button"
              onClick={() => setDiscoverResult(null)}
              className="rounded p-1 text-fg-muted hover:bg-surface-2"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4" />
            </button>
          </CardContent>
        </Card>
      ) : null}
      {discoverMut.isError ? (
        <Card className="border-danger/40 bg-danger/5">
          <CardContent className="py-3 text-sm text-danger">
            Discovery failed: {String((discoverMut.error as Error)?.message)}
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <ListSkeleton />
      ) : error ? (
        <Card>
          <CardContent className="py-6 text-sm text-danger">
            Failed to load conferences. Refresh to retry.
          </CardContent>
        </Card>
      ) : !data || data.items.length === 0 ? (
        <EmptyState message="No conferences match this filter. Try widening the status set." />
      ) : (
        <div className="flex flex-col gap-3">
          {data.items.map((c) => (
            <ConferenceRow key={c.id} c={c} />
          ))}
        </div>
      )}

      {data && data.items.length > 0 ? (
        <p className="text-xs text-fg-subtle">
          {data.items.length} of {data.total}
        </p>
      ) : null}

      {showImport ? <ImportPastDialog onClose={() => setShowImport(false)} /> : null}
      {showNewDialog ? (
        <NewConferenceDialog
          onClose={() => setShowNewDialog(false)}
          onCreated={(conferenceId) => {
            setShowNewDialog(false);
            queryClient.invalidateQueries({ queryKey: ["conferences"] });
            navigate({ to: "/conferences/$id", params: { id: conferenceId } });
          }}
        />
      ) : null}
    </div>
  );
}

function ConferenceRow({ c }: { c: import("@/lib/api-types").ConferenceListItem }) {
  const overall = c.overall_score ?? null;
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { label: meLabel } = useMe();

  const deleteMut = useMutation({
    mutationFn: () => conferencesApi.delete(c.id, "user_delete"),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["conferences"] }),
  });

  const decideMut = useMutation({
    mutationFn: (decision: "approved" | "rejected") =>
      conferencesApi.createDecision(c.id, {
        decision,
        reason: null,
        decided_by_label: meLabel || "user_inline",
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["conferences"] }),
  });

  const onDelete = () => {
    if (deleteMut.isPending) return;
    if (
      !window.confirm(
        `Delete "${c.name}"? This removes the conference and all of its matches, ` +
          `decisions, raw pages, and team recommendations. Can't be undone.`,
      )
    ) {
      return;
    }
    deleteMut.mutate();
  };

  const stop = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const decidedApproved = c.status === "approved";
  const decidedRejected = c.status === "rejected";

  return (
    <div
      className="group relative cursor-pointer rounded-lg border border-border bg-surface-1 p-4 transition-colors hover:border-border-strong hover:bg-surface-2"
      onClick={() =>
        navigate({ to: "/conferences/$id", params: { id: c.id } })
      }
      role="link"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate({ to: "/conferences/$id", params: { id: c.id } });
        }
      }}
    >
      <div className="flex items-start gap-4 pr-24">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 truncate">
            <h2 className="truncate text-base font-medium text-fg">{c.name}</h2>
            <StatusPill status={c.status} />
            {c.is_virtual ? <Badge variant="muted">Virtual</Badge> : null}
            {c.previously_attended ? (
              <Badge variant="success" title="Your team has attended a past edition of this conference series">
                Previously attended
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-fg-muted">
            {c.start_date ?? "TBD"}
            {c.location_city || c.location_country
              ? ` · ${[c.location_city, c.location_country].filter(Boolean).join(", ")}`
              : ""}
          </p>
          {c.topics && c.topics.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {c.topics.slice(0, 6).map((t) => (
                <Badge key={t} variant="muted">
                  {t}
                </Badge>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex w-32 flex-col items-end gap-1">
          <div className="flex items-baseline gap-1 tabular-nums">
            <span className="text-2xl font-semibold">
              {overall !== null ? Math.round(overall * 100) : "—"}
            </span>
            <span className="text-xs text-fg-muted">/ 100</span>
          </div>
          {overall !== null ? <Progress value={overall} className="w-full" /> : null}
          <p className="text-xs font-medium uppercase tracking-wider text-fg-muted">
            overall fit
          </p>
        </div>
      </div>
      {/* Action stack — top-right corner, vertical, away from score */}
      <div className="absolute right-2 top-2 z-10 flex flex-col gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          onClick={(e) => {
            stop(e);
            if (decidedApproved || decideMut.isPending) return;
            decideMut.mutate("approved");
          }}
          disabled={decideMut.isPending || decidedApproved}
          title={decidedApproved ? "Already approved" : "Approve"}
          aria-label={`Approve ${c.name}`}
          className="rounded p-1.5 text-fg-muted hover:bg-success/10 hover:text-success disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Check className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={(e) => {
            stop(e);
            if (decidedRejected || decideMut.isPending) return;
            decideMut.mutate("rejected");
          }}
          disabled={decideMut.isPending || decidedRejected}
          title={decidedRejected ? "Already rejected" : "Reject"}
          aria-label={`Reject ${c.name}`}
          className="rounded p-1.5 text-fg-muted hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
        >
          <X className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={(e) => {
            stop(e);
            onDelete();
          }}
          disabled={deleteMut.isPending}
          title={deleteMut.isPending ? "Deleting…" : "Delete"}
          aria-label={`Delete ${c.name}`}
          className="rounded p-1.5 text-fg-muted hover:bg-danger/10 hover:text-danger"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-1/2" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-3 w-1/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
