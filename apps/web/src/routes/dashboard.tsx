/**
 * /dashboard — top events + global map + lightweight agent prompt.
 *
 * Sections:
 *   - 3 roll-up stat cards (upcoming approved · pending review · CFP closing)
 *   - Dark world map: one dot per country, sized by event count
 *   - Top picks: 6 per page, with prev/next pagination so the LLM only
 *     scores 6 cards' worth of detail per page load instead of 50+ at once
 *   - Ask Scout: small prompt-and-answer panel (one-shot, no session)
 */

import { useQuery } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { AgentChatPanel } from "@/components/agent/AgentChatPanel";
import { StatusPill } from "@/components/conferences/StatusPill";
import { WorldMap } from "@/components/dashboard/WorldMap";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

const PAGE_SIZE = 6;

function DashboardPage() {
  const statsQ = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: () => conferencesApi.dashboardStats(),
  });
  // Pull a much larger pool so we can paginate locally — far cheaper
  // than re-issuing the list endpoint per page, and the per-card LLM
  // queries (rationale + SMEs) only fire for the currently-visible
  // 6 cards.
  const allQ = useQuery({
    queryKey: ["dashboard", "top-conferences"],
    queryFn: () => conferencesApi.list({ per_page: 100, sort: "score" }),
  });
  const [page, setPage] = useState(0);

  const stats = statsQ.data;
  const allItems = useMemo(() => allQ.data?.items ?? [], [allQ.data]);
  const totalPages = Math.max(1, Math.ceil(allItems.length / PAGE_SIZE));
  const pageItems = allItems.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // Geocoded conferences — one item per non-virtual conference whose
  // location resolved to lat/lng. The map clusters them by city.
  const mapQ = useQuery({
    queryKey: ["dashboard", "by-location"],
    queryFn: () => conferencesApi.statsByLocation(),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dashboard"
        description="Where to go next: top-ranked AI events, global distribution, recommended SMEs."
      />

      {/* Three roll-up stats (low-coverage SMEs card removed; that's a
          /smes-page concern, not a dashboard one) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
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
      </div>

      {/* Map (left) + Ask Scout chat (right). On lg+ they split the row
          50/50 and BOTH live in a fixed-height container so the chat's
          message stream scrolls inside its pane (instead of pushing the
          rest of the dashboard down as the conversation grows) and so
          the map fills its half exactly. Below lg they stack. */}
      <div className="grid grid-cols-1 gap-4 lg:h-[640px] lg:grid-cols-2">
        <div className="h-[640px] min-h-0 lg:h-auto">
          <WorldMap items={mapQ.data?.items ?? []} />
        </div>
        <div className="h-[640px] min-h-0 lg:h-auto">
          <AgentChatPanel
            title="Ask Scout"
            storageKey="scout-dashboard-chat-session-id"
            defaultSessionTitle="Dashboard chat"
            placeholder="e.g. 'AI conferences in Europe this quarter and who to send'"
          />
        </div>
      </div>

      {/* Top conferences — paginated */}
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Top picks</h2>
        <div className="flex items-center gap-3">
          <Link
            to="/conferences"
            className="text-xs text-accent hover:underline"
          >
            See all →
          </Link>
        </div>
      </div>

      {allQ.isLoading ? (
        <CardSkeletonGrid />
      ) : allItems.length === 0 ? (
        <EmptyState message="No conferences yet. Click 'Discover more' on /conferences to fetch a fresh batch." />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {pageItems.map((c) => (
              <ConferenceFactCard key={c.id} c={c} />
            ))}
          </div>
          <Pagination
            page={page}
            total={allItems.length}
            pageSize={PAGE_SIZE}
            onPage={setPage}
          />
        </>
      )}

    </div>
  );
}

// ---------------------------------------------------------------------------
// One conference card — the WHO / WHAT / WHEN / WHERE / WHY layout.
// ---------------------------------------------------------------------------
function ConferenceFactCard({
  c,
}: {
  c: import("@/lib/api-types").ConferenceListItem;
}) {
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
  const where = c.is_virtual
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

// ---------------------------------------------------------------------------
// Pagination strip
// ---------------------------------------------------------------------------
function Pagination({
  page,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-fg-muted">
        Showing {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPage(Math.max(0, page - 1))}
          disabled={page === 0}
        >
          ← Previous
        </Button>
        <span className="px-2 text-xs text-fg-muted tabular-nums">
          Page {page + 1} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPage(Math.min(totalPages - 1, page + 1))}
          disabled={page >= totalPages - 1}
        >
          Next →
        </Button>
      </div>
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

/**
 * Soft info banner for settings pages. Appears just below PageHeader.
 * Gives a "what is this page, what should I do here" explainer without
 * being a full tutorial section.
 */
export function PageBanner({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-accent/20 bg-accent/5 px-4 py-3 text-sm leading-relaxed text-fg-muted">
      {children}
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
