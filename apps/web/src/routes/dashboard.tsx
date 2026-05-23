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

import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";

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
import { agentApi, conferencesApi } from "@/lib/api";

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

      {/* World map — city-level dots, clickable for the underlying events */}
      <WorldMap items={mapQ.data?.items ?? []} />

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

      {/* Agent quick-ask panel */}
      <AskScout />
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

// ---------------------------------------------------------------------------
// Embedded one-shot agent prompt — for the user who just wants to ask
// a quick question without leaving the dashboard.
// ---------------------------------------------------------------------------
function AskScout() {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: async (prompt: string) => {
      // Lazily create / reuse a single dashboard session.
      let sid = sessionId;
      if (!sid) {
        const created = await agentApi.createSession("Dashboard quick ask");
        sid = created.id;
        setSessionId(sid);
      }
      const reply = await agentApi.ask(sid, prompt);
      return reply.content;
    },
    onSuccess: (content) => setAnswer(content),
  });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Ask Scout</CardTitle>
        <CardDescription>
          Quick question about your conferences, SMEs, or messaging. Threaded
          conversations live in{" "}
          <Link to="/settings" className="text-accent hover:underline">
            Settings → Agent chat
          </Link>
          .
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!q.trim() || mut.isPending) return;
            mut.mutate(q.trim());
          }}
        >
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.currentTarget.value)}
            placeholder="e.g. 'What AI conferences in Europe close their CFP this month?'"
            className="flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm"
          />
          <Button type="submit" disabled={mut.isPending || !q.trim()}>
            {mut.isPending ? "Thinking…" : "Ask"}
          </Button>
        </form>
        {mut.isError && (
          <div className="rounded border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
            {String((mut.error as Error)?.message)}
          </div>
        )}
        {answer && (
          <div className="rounded-md border border-border-subtle bg-surface-2 p-3 text-sm text-fg whitespace-pre-wrap">
            {answer}
          </div>
        )}
      </CardContent>
    </Card>
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
