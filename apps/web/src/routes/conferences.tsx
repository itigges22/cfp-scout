/**
 * /conferences — ranked list (plan 20).
 *
 * Server-side filter by status, server-side sort by score|date|name.
 * Each row links to the detail page. Bulk actions + CSV export are
 * deferred to a future pass.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
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

type SortOpt = "score" | "date" | "name";

function ConferencesPage() {
  const [status, setStatus] = useState<string | null>(null);
  const [sort, setSort] = useState<SortOpt>("score");
  const [showNewDialog, setShowNewDialog] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const queryKey = useMemo(
    () => ["conferences", { status, sort }] as const,
    [status, sort],
  );
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () =>
      conferencesApi.list({
        sort,
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
          {(["score", "date", "name"] as const).map((opt) => (
            <Button
              key={opt}
              variant={sort === opt ? "default" : "ghost"}
              size="sm"
              onClick={() => setSort(opt)}
            >
              {opt}
            </Button>
          ))}
        </div>
      </div>

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
  const deleteMut = useMutation({
    mutationFn: () => conferencesApi.delete(c.id, "user_delete"),
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

  return (
    <div className="group relative flex items-start gap-4 rounded-lg border border-border bg-surface-1 p-4 transition-colors hover:border-border-strong hover:bg-surface-2">
      <Link
        to="/conferences/$id"
        params={{ id: c.id }}
        className="min-w-0 flex-1"
      >
        <div className="flex items-center gap-2 truncate">
          <h2 className="truncate text-base font-medium text-fg">{c.name}</h2>
          <StatusPill status={c.status} />
          {c.is_virtual ? <Badge variant="muted">Virtual</Badge> : null}
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
      </Link>
      <div className="flex w-44 flex-col items-end gap-2">
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
      <button
        type="button"
        onClick={onDelete}
        disabled={deleteMut.isPending}
        title={deleteMut.isPending ? "Deleting…" : "Delete conference"}
        aria-label={`Delete ${c.name}`}
        className="absolute right-2 top-2 rounded p-1.5 text-fg-muted opacity-0 transition-opacity hover:bg-danger/10 hover:text-danger group-hover:opacity-100 focus:opacity-100"
      >
        <Trash2 className="h-4 w-4" />
      </button>
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
