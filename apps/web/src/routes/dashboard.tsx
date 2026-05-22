/**
 * /dashboard — overview (plan 20).
 *
 * Four stat cards + top-5 ranked conferences. Wired to
 * GET /api/v1/conferences/stats/dashboard. Filter bar + saved views are
 * deferred to a future pass; the conferences list lives at /conferences.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";

import { StatusPill } from "@/components/conferences/StatusPill";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { conferencesApi } from "@/lib/api";
import type { DashboardStats } from "@/lib/api-types";

export const Route = createFileRoute("/dashboard")({
  component: DashboardPage,
});

function DashboardPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: () => conferencesApi.dashboardStats(),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dashboard"
        description="Upcoming conferences, pending reviews, CFP windows."
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Upcoming approved"
          hint="next 90 days"
          value={data?.cards.upcoming_approved}
          loading={isLoading}
          error={!!error}
        />
        <StatCard
          title="Pending review"
          hint="needs your attention"
          value={data?.cards.pending_review}
          loading={isLoading}
          error={!!error}
        />
        <StatCard
          title="CFP closing"
          hint="within 30 days"
          value={data?.cards.cfp_closing_soon}
          loading={isLoading}
          error={!!error}
        />
        <StatCard
          title="Low-coverage SMEs"
          hint="missing topics or audiences"
          value={data?.cards.low_coverage_smes}
          loading={isLoading}
          error={!!error}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Top ranked</CardTitle>
          <CardDescription>
            Highest overall fit score across non-quarantined conferences.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : error ? (
            <EmptyState message="Could not load dashboard stats." />
          ) : !data || data.top_conferences.length === 0 ? (
            <EmptyState message="No conferences yet. Once the scraper + matcher have run, top picks land here." />
          ) : (
            <TopList rows={data.top_conferences} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  title,
  hint,
  value,
  loading,
  error,
}: {
  title: string;
  hint: string;
  value: number | undefined;
  loading: boolean;
  error: boolean;
}) {
  return (
    <Card>
      <CardHeader className="p-4">
        <CardDescription className="text-xs uppercase tracking-wider">
          {title}
        </CardDescription>
        <CardTitle className="text-3xl font-semibold tabular-nums">
          {error ? "—" : loading ? <Skeleton className="h-7 w-12" /> : (value ?? 0).toString()}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4 pt-0 text-xs text-fg-subtle">{hint}</CardContent>
    </Card>
  );
}

function TopList({ rows }: { rows: DashboardStats["top_conferences"] }) {
  return (
    <ul className="divide-y divide-border-subtle">
      {rows.map((r) => (
        <li key={r.id}>
          <Link
            to="/conferences/$id"
            params={{ id: r.id }}
            className="flex items-center gap-3 py-2 transition-colors hover:bg-surface-2"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 truncate">
                <span className="truncate text-sm font-medium">{r.name}</span>
                <StatusPill status={r.status} />
              </div>
              <p className="text-xs text-fg-muted">{r.start_date ?? "Dates TBD"}</p>
            </div>
            <div className="flex w-36 items-center gap-2">
              <Progress value={r.overall_score ?? 0} className="flex-1" />
              <span className="w-8 text-right text-sm font-medium tabular-nums">
                {r.overall_score === null ? "—" : Math.round(r.overall_score * 100)}
              </span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

// ---- exported because conferences.tsx + others re-use these ---------------

export function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex flex-col gap-1">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-sm text-fg-muted">{description}</p>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center rounded-md border border-dashed border-border-strong bg-surface-2 py-10">
      <p className="text-sm text-fg-muted">{message}</p>
    </div>
  );
}
