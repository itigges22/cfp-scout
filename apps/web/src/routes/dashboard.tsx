/**
 * /dashboard — at-a-glance view of the top conferences.
 *
 * Replaces the prior generic-stat-cards page. Now shows one rich card
 * per top-scoring conference with the operator-facing facts:
 *   - what     : conference name, status, score
 *   - when     : start/end dates + CFP close date
 *   - where    : city + country (or 'virtual')
 *   - why      : rationale from the matcher
 *   - who      : top recommended SMEs from the SME ranker
 *   - apply    : direct link to the CFP URL
 *
 * The four old roll-up stat cards stay at the top for quick scanning.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";

import { StatusPill } from "@/components/conferences/StatusPill";
import { Badge } from "@/components/ui/badge";
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

export const Route = createFileRoute("/dashboard")({
  component: DashboardPage,
});

function DashboardPage() {
  const statsQ = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: () => conferencesApi.dashboardStats(),
  });
  // Pull the top 6 conferences by score with their full ListItem shape
  // (name, location, dates, cfp_url, cfp_close_at, score, status, topics).
  const topQ = useQuery({
    queryKey: ["dashboard", "top-conferences"],
    queryFn: () => conferencesApi.list({ per_page: 6, sort: "score" }),
  });

  const stats = statsQ.data;
  const topItems = topQ.data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dashboard"
        description="Where to go next: top-ranked AI events with CFP dates, locations, and recommended SMEs."
      />

      {/* Top-line numbers */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Upcoming approved"
          hint="next 90 days"
          value={stats?.cards.upcoming_approved}
          loading={statsQ.isLoading}
          error={!!statsQ.error}
        />
        <StatCard
          title="Pending review"
          hint="needs your attention"
          value={stats?.cards.pending_review}
          loading={statsQ.isLoading}
          error={!!statsQ.error}
        />
        <StatCard
          title="CFP closing"
          hint="within 30 days"
          value={stats?.cards.cfp_closing_soon}
          loading={statsQ.isLoading}
          error={!!statsQ.error}
        />
        <StatCard
          title="Low-coverage SMEs"
          hint="missing topics or audiences"
          value={stats?.cards.low_coverage_smes}
          loading={statsQ.isLoading}
          error={!!statsQ.error}
        />
      </div>

      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Top picks</h2>
        <Link to="/conferences" className="text-xs text-accent hover:underline">
          See all conferences →
        </Link>
      </div>

      {topQ.isLoading ? (
        <CardSkeletonGrid />
      ) : topItems.length === 0 ? (
        <EmptyState message="No conferences yet. Click 'Discover more' on /conferences to fetch a fresh batch." />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {topItems.map((c) => (
            <ConferenceFactCard key={c.id} c={c} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The headline component: one conference, all the facts an operator needs
// before deciding "should we go?".
// ---------------------------------------------------------------------------
function ConferenceFactCard({
  c,
}: {
  c: import("@/lib/api-types").ConferenceListItem;
}) {
  // Per-card extras: match (rationale) + smes (recommended team).
  const matchQ = useQuery({
    queryKey: ["conferences", c.id, "match"],
    queryFn: () => conferencesApi.match(c.id),
    staleTime: 60_000,
  });
  const smesQ = useQuery({
    queryKey: ["conferences", c.id, "smes"],
    queryFn: () => conferencesApi.smes(c.id, 3),
    staleTime: 60_000,
  });

  const overall = c.overall_score ?? null;
  const overallPct = overall === null ? "—" : Math.round(overall * 100);
  const where =
    c.is_virtual
      ? "Virtual"
      : [c.location_city, c.location_country].filter(Boolean).join(", ");
  const rationale = matchQ.data?.match?.rationale_text ?? "";
  const topSmes = smesQ.data?.above_gate ?? smesQ.data?.near_misses ?? [];

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <Link
              to="/conferences/$id"
              params={{ id: c.id }}
              className="block truncate text-base font-semibold text-fg hover:underline"
            >
              {c.name}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <StatusPill status={c.status} />
              {c.topics?.slice(0, 3).map((t) => (
                <Badge key={t} variant="muted">
                  {t}
                </Badge>
              ))}
            </div>
          </div>
          <div className="flex w-16 flex-col items-end gap-1">
            <div className="flex items-baseline gap-1 tabular-nums">
              <span className="text-2xl font-semibold">{overallPct}</span>
              <span className="text-xs text-fg-muted">/100</span>
            </div>
            {overall !== null && <Progress value={overall} className="w-full" />}
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3 pt-0 text-sm">
        <FactGrid c={c} where={where} />

        {/* Why */}
        <Section title="Why">
          {matchQ.isLoading ? (
            <Skeleton className="h-12 w-full" />
          ) : rationale ? (
            <p className="text-sm leading-snug text-fg">{rationale}</p>
          ) : (
            <p className="text-xs italic text-fg-muted">
              Matcher hasn't produced a rationale yet.
            </p>
          )}
        </Section>

        {/* Who */}
        <Section title="Who">
          {smesQ.isLoading ? (
            <Skeleton className="h-8 w-2/3" />
          ) : topSmes.length === 0 ? (
            <p className="text-xs italic text-fg-muted">
              No SME above gate. Fill in SME bios + topic assignments.
            </p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {topSmes.slice(0, 3).map((sme) => (
                <li
                  key={sme.sme_id}
                  className="inline-flex items-baseline gap-1 rounded bg-surface-2 px-2 py-0.5"
                >
                  <span className="text-sm font-medium">{sme.full_name}</span>
                  <span className="text-xs tabular-nums text-fg-muted">
                    {Math.round((sme.composite ?? 0) * 100)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        {/* Apply call-to-action */}
        {c.cfp_url ? (
          <a
            href={c.cfp_url}
            target="_blank"
            rel="noreferrer noopener"
            className="mt-auto inline-flex w-fit items-center gap-1 rounded bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
          >
            Apply / view CFP ↗
          </a>
        ) : (
          <Link
            to="/conferences/$id"
            params={{ id: c.id }}
            className="mt-auto inline-flex w-fit items-center text-sm text-accent underline-offset-2 hover:underline"
          >
            Open details →
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

function FactGrid({
  c,
  where,
}: {
  c: import("@/lib/api-types").ConferenceListItem;
  where: string;
}) {
  const dateRange = c.start_date
    ? c.end_date && c.end_date !== c.start_date
      ? `${c.start_date} – ${c.end_date}`
      : c.start_date
    : "Dates TBD";
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
      <Fact label="When">{dateRange}</Fact>
      <Fact label="Where">{where || "—"}</Fact>
      <Fact label="CFP closes">{c.cfp_close_at ?? "—"}</Fact>
      <Fact label="What" title={c.name}>
        {c.topics?.length ? c.topics.slice(0, 3).join(", ") : "AI event"}
      </Fact>
    </dl>
  );
}

function Fact({
  label,
  children,
  title,
}: {
  label: string;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-fg-muted">{label}</dt>
      <dd className="truncate text-sm text-fg" title={title}>
        {children}
      </dd>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wider text-fg-muted">{title}</p>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function CardSkeletonGrid() {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {[0, 1, 2, 3].map((i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-2/3" />
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-12 w-full" />
          </CardContent>
        </Card>
      ))}
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
