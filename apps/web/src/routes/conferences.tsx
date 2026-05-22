/**
 * /conferences — ranked list (plan 20).
 *
 * Server-side filter by status, server-side sort by score|date|name.
 * Each row links to the detail page. Bulk actions + CSV export are
 * deferred to a future pass.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { StatusPill } from "@/components/conferences/StatusPill";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
    </div>
  );
}

function ConferenceRow({ c }: { c: import("@/lib/api-types").ConferenceListItem }) {
  const overall = c.overall_score ?? null;
  return (
    <Link
      to="/conferences/$id"
      params={{ id: c.id }}
      className="block rounded-lg border border-border bg-surface-1 p-4 transition-colors hover:border-border-strong hover:bg-surface-2"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
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
        </div>
        <div className="flex w-44 flex-col items-end gap-2">
          <div className="flex items-baseline gap-1 tabular-nums">
            <span className="text-2xl font-semibold">
              {overall !== null ? Math.round(overall * 100) : "—"}
            </span>
            <span className="text-xs text-fg-muted">/ 100</span>
          </div>
          {overall !== null ? <Progress value={overall} className="w-full" /> : null}
          <p className="text-[10px] uppercase tracking-wider text-fg-subtle">
            overall fit
          </p>
        </div>
      </div>
    </Link>
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
