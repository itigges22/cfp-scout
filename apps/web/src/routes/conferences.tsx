/**
 * /conferences — ranked list (plan 20).
 *
 * Server-side filter by status, server-side sort by score|date|name.
 * Each row links to the detail page. Bulk actions + CSV export are
 * deferred to a future pass.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Check, Sparkles, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { NewConferenceDialog } from "@/components/conferences/NewConferenceDialog";
import { StatusPill } from "@/components/conferences/StatusPill";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { conferencesApi } from "@/lib/api";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/conferences")({
  component: ConferencesPage,
});

const STATUS_FILTERS = [
  { value: null, label: "All open" },
  { value: "approved", label: "Approved" },
  { value: "needs_review", label: "Needs review" },
  { value: "needs_sme_review", label: "Needs SME review" },
  { value: "low_messaging_fit", label: "Low messaging fit" },
] as const;

type SortOpt = "score" | "messaging" | "pillar" | "sme" | "date" | "name";

// Sort buttons + labels. Order matters: leftmost is the default.
// "score" = combined overall_score (messaging+pillar+sme weighted).
// The three component sorts (messaging/pillar/sme) let the operator
// drill into which dimension drives a conference's rank, since the
// three signals don't always agree (an Agentic-named event peaks
// hard on pillar but is moderate on raw messaging; a vLLM Meetup is
// the inverse).
const SORT_OPTS: { value: SortOpt; label: string }[] = [
  { value: "score", label: "Overall" },
  { value: "messaging", label: "Messaging" },
  { value: "pillar", label: "Pillar" },
  { value: "sme", label: "SME" },
  { value: "date", label: "Date" },
  { value: "name", label: "Name" },
];

type AttendanceFilter = "all" | "new" | "returning";
const ATTENDANCE_OPTS: { value: AttendanceFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "new", label: "New only" },
  { value: "returning", label: "Previously attended" },
];

function ConferencesPage() {
  const [status, setStatus] = useState<string | null>(null);
  const [sort, setSort] = useState<SortOpt>("score");
  const [attendanceFilter, setAttendanceFilter] = useState<AttendanceFilter>("all");
  const [showNewDialog, setShowNewDialog] = useState(false);
  const [discoverResult, setDiscoverResult] = useState<{
    new_conferences: number;
    updated_conferences: number;
    total_in_feed: number;
    matched_filter: number;
  } | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const discoverMut = useMutation({
    mutationFn: async () => {
      const res = await fetch(
        "/api/v1/admin/discovery/ingest-feed",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ only_ai: true, future_only: true }),
        },
      );
      if (!res.ok) throw new Error(`Discovery failed: HTTP ${res.status}`);
      return (await res.json()) as {
        new_conferences: number;
        updated_conferences: number;
        total_in_feed: number;
        matched_filter: number;
      };
    },
    onSuccess: (data) => {
      setDiscoverResult(data);
      queryClient.invalidateQueries({ queryKey: ["conferences"] });
    },
  });

  const queryKey = useMemo(
    () => ["conferences", { status, sort, attendanceFilter }] as const,
    [status, sort, attendanceFilter],
  );
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () =>
      conferencesApi.list({
        sort,
        attendance_filter: attendanceFilter,
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

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => setShowNewDialog(true)}>+ New conference</Button>
        <Button
          variant="outline"
          onClick={() => discoverMut.mutate()}
          disabled={discoverMut.isPending}
        >
          <Sparkles className="mr-1.5 h-4 w-4" />
          {discoverMut.isPending ? "Discovering…" : "Discover more"}
        </Button>
        <span className="mx-2 hidden h-5 w-px bg-border md:inline-block" />
        {STATUS_FILTERS.map((s) => (
          <Button
            key={String(s.value)}
            variant={status === s.value ? "default" : "outline"}
            size="sm"
            onClick={() => setStatus(s.value)}
          >
            {s.label}
          </Button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-fg-muted">Sort:</span>
          {SORT_OPTS.map((opt) => (
            <Button
              key={opt.value}
              variant={sort === opt.value ? "default" : "ghost"}
              size="sm"
              onClick={() => setSort(opt.value)}
            >
              {opt.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Past-attendance filter row — separate from status/sort because
          it's a different axis: "what fraction of the dataset" rather
          than "which status bucket" or "how ranked". */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-fg-muted">Attendance:</span>
        {ATTENDANCE_OPTS.map((opt) => (
          <Button
            key={opt.value}
            variant={attendanceFilter === opt.value ? "default" : "outline"}
            size="sm"
            onClick={() => setAttendanceFilter(opt.value)}
          >
            {opt.label}
          </Button>
        ))}
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
        decided_by_label: "user_inline",
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
