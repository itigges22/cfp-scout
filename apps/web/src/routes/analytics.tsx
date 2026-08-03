/**
 * /analytics — the graph suite.
 *
 * Every series arrives pre-binned from GET /api/v1/analytics/overview;
 * this page draws axes and shapes, never aggregates. The filter bar
 * narrows the conference set server-side, so all charts always answer
 * the same filtered question. The number cards on pillar/SME pages stay
 * where they are — this page is for shape and trend, not glancing.
 *
 * Charts are styled for the dark theme by hand: recharts defaults (black
 * ticks, white tooltips, saturated fills) are unreadable on bg-canvas,
 * which is exactly the complaint that caused this file's second draft.
 */

import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { analyticsApi, conferencesApi, fetchEventKinds, pillarsApi } from "@/lib/api";

export const Route = createFileRoute("/analytics")({
  component: AnalyticsPage,
});

// One palette, used everywhere: a light red for "workload/urgency"
// series, a light indigo for "shape of the corpus" series. Both chosen
// for WCAG contrast on the dark canvas: indigo-300 (#a5b4fc) is ~8.6:1
// and red-400 (#f87171) is ~5.4:1 against #18181b — comfortably past the
// 3:1 non-text minimum. Tick text is zinc-300 at 13px (~11:1), past the
// 4.5:1 small-text minimum.
const RED = "#f87171";
const INDIGO = "#a5b4fc";
const GRID = "#3f3f46";
const TICK = { fontSize: 13, fill: "#d4d4d8" } as const;

const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: "#18181b",
    border: "1px solid #3f3f46",
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: "#fafafa", fontWeight: 600 },
  itemStyle: { color: "#d4d4d8" },
  cursor: false,
} as const;

/** "low_messaging_fit" → "Low messaging fit" — display concern only. */
function pretty(s: string): string {
  return (s.charAt(0).toUpperCase() + s.slice(1)).replace(/_/g, " ");
}

function AnalyticsPage() {
  const [pillarId, setPillarId] = useState("");
  const [country, setCountry] = useState("");
  const [months, setMonths] = useState(12);
  const [status, setStatus] = useState("");
  const [eventKind, setEventKind] = useState("");
  const [includeVirtual, setIncludeVirtual] = useState(true);
  const [startsAfter, setStartsAfter] = useState("");
  const [startsBefore, setStartsBefore] = useState("");
  const kinds = useQuery({
    queryKey: ["event-kinds"],
    queryFn: fetchEventKinds,
    staleTime: 5 * 60_000,
  });

  const pillars = useQuery({
    queryKey: ["pillars"],
    queryFn: () => pillarsApi.list(),
    staleTime: 60_000,
  });
  // The "right now" trio that used to sit on the dashboard — action
  // counts belong next to the analysis that explains them.
  const statsQ = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: () => conferencesApi.dashboardStats(),
  });
  const q = useQuery({
    queryKey: [
      "analytics",
      { pillarId, country, months, status, eventKind, includeVirtual, startsAfter, startsBefore },
    ],
    queryFn: () =>
      analyticsApi.overview({
        ...(pillarId ? { pillar_id: pillarId } : {}),
        ...(country.trim() ? { country: country.trim().toUpperCase() } : {}),
        ...(status ? { status: [status] } : {}),
        ...(eventKind ? { event_kind: [eventKind] } : {}),
        ...(startsAfter ? { starts_after: startsAfter } : {}),
        ...(startsBefore ? { starts_before: startsBefore } : {}),
        include_virtual: includeVirtual,
        months,
      }),
  });

  const hasOutcomes = (q.data?.outcomes_by_month ?? []).some(
    (m) => Number(m.spend_usd ?? 0) > 0 || Number(m.leads ?? 0) > 0,
  );

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
        <p className="mt-0.5 text-sm text-fg-muted">
          The corpus and your team&rsquo;s outcomes, as shapes. Filters apply
          to every chart at once.
        </p>
      </div>

      {/* Filter bar — server-side filters, shared by every chart */}
      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-border bg-surface p-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-fg-muted">Pillar</span>
          <select
            className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
            value={pillarId}
            onChange={(e) => setPillarId(e.currentTarget.value)}
          >
            <option value="">All pillars</option>
            {(pillars.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-fg-muted">Country</span>
          <input
            className="h-8 w-20 rounded-md border border-border bg-surface px-2 text-sm text-fg"
            placeholder="US"
            maxLength={2}
            value={country}
            onChange={(e) => setCountry(e.currentTarget.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-fg-muted">Status</span>
          <select
            className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
            value={status}
            onChange={(e) => setStatus(e.currentTarget.value)}
          >
            <option value="">All statuses</option>
            {["approved", "needs_sme_review", "low_messaging_fit", "vetoed", "rejected"].map(
              (s) => (
                <option key={s} value={s}>
                  {pretty(s)}
                </option>
              ),
            )}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-fg-muted">Type</span>
          <select
            className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
            value={eventKind}
            onChange={(e) => setEventKind(e.currentTarget.value)}
          >
            <option value="">All types</option>
            {(kinds.data ?? []).map((k) => (
              <option key={k} value={k}>
                {pretty(k)}
              </option>
            ))}
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
        <label className="flex items-center gap-2 pb-1">
          <input
            type="checkbox"
            checked={includeVirtual}
            onChange={(e) => setIncludeVirtual(e.currentTarget.checked)}
          />
          <span className="text-xs text-fg-muted">Include virtual</span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-fg-muted">Window</span>
          <select
            className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
            value={months}
            onChange={(e) => setMonths(Number(e.currentTarget.value))}
          >
            <option value={6}>6 months</option>
            <option value={12}>12 months</option>
            <option value={24}>24 months</option>
          </select>
        </label>
        {q.data ? (
          <span className="ml-auto pb-1 text-sm text-fg-muted">
            {q.data.conference_count.toLocaleString()} conferences in view
          </span>
        ) : null}
      </div>

      {q.isLoading ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      ) : q.isError || !q.data ? (
        <p className="text-sm text-danger">Could not load analytics.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {/* What the matcher is looking at for THIS view */}
          <Card className="lg:col-span-2 xl:col-span-3">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Matcher signals</CardTitle>
              <p className="mt-0.5 text-xs text-fg-muted">
                What the matching algorithm saw for the conferences in view —
                signal averages, judge verdicts, and the live weights it used.
              </p>
            </CardHeader>
            <CardContent className="flex flex-wrap items-start gap-x-8 gap-y-3 pt-0">
              <Sig
                label="Upcoming approved (90d)"
                value={statsQ.data?.cards.upcoming_approved ?? "—"}
              />
              <Sig
                label="Pending review"
                value={statsQ.data?.cards.pending_review ?? "—"}
              />
              <Sig
                label="CFP closing (30d)"
                value={statsQ.data?.cards.cfp_closing_soon ?? "—"}
              />
              <Sig label="Scored" value={q.data.matcher_signals.scored} />
              <Sig
                label="Avg strategy fit"
                value={
                  q.data.matcher_signals.avg_fit != null
                    ? Math.round(q.data.matcher_signals.avg_fit * 100)
                    : "—"
                }
              />
              <Sig
                label="Avg speaker fit"
                value={
                  q.data.matcher_signals.avg_speakers != null
                    ? Math.round(q.data.matcher_signals.avg_speakers * 100)
                    : "—"
                }
              />
              <div className="flex flex-col gap-1">
                <span className="text-xs text-fg-muted">Judge verdicts</span>
                <div className="flex flex-wrap gap-1.5">
                  {q.data.matcher_signals.judge_verdicts.map((v) => (
                    <span
                      key={String(v.verdict)}
                      className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs text-fg-muted"
                    >
                      {pretty(String(v.verdict))}: {String(v.count)}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs text-fg-muted">Blend &amp; gates</span>
                <p className="text-xs text-fg-muted">
                  overall = {q.data.matcher_signals.weights.fit} × fit +{" "}
                  {q.data.matcher_signals.weights.speakers} × speakers · fit gate{" "}
                  {q.data.matcher_signals.gates.messaging} · speaker gate{" "}
                  {q.data.matcher_signals.gates.speakers}
                </p>
                <p className="text-xs text-fg-subtle">
                  SME dimensions:{" "}
                  {Object.entries(q.data.matcher_signals.sme_dimension_weights)
                    .map(([k, w]) => `${k} ${w}`)
                    .join(" · ")}
                </p>
              </div>
            </CardContent>
          </Card>

          <ChartCard
            title="Pipeline by status"
            sub="Where the filtered corpus sits in the funnel"
          >
            <BarChart
              data={q.data.status_funnel.map((r) => ({
                ...r,
                status: pretty(String(r.status)),
              }))}
              margin={{ top: 4, right: 8, bottom: 4, left: -16 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
              <XAxis dataKey="status" tick={TICK} tickLine={false} axisLine={false} />
              <YAxis tick={TICK} tickLine={false} axisLine={false} />
              <Tooltip {...TOOLTIP_STYLE} />
              <Bar dataKey="count" name="Conferences" fill={INDIGO} radius={[4, 4, 0, 0]} maxBarSize={72} />
            </BarChart>
          </ChartCard>

          <ChartCard
            title="Overall-score distribution"
            sub="How well the corpus matches your strategy (0–100)"
          >
            <BarChart
              data={q.data.score_histogram}
              margin={{ top: 4, right: 8, bottom: 4, left: -16 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
              <XAxis dataKey="bucket" tick={TICK} tickLine={false} axisLine={false} />
              <YAxis tick={TICK} tickLine={false} axisLine={false} />
              <Tooltip {...TOOLTIP_STYLE} />
              <Bar dataKey="count" name="Conferences" fill={INDIGO} radius={[4, 4, 0, 0]} maxBarSize={48} />
            </BarChart>
          </ChartCard>

          <ChartCard
            title="CFP deadlines ahead"
            sub="Open CFPs closing per month — your submission workload"
          >
            <BarChart
              data={q.data.cfp_deadlines_by_month}
              margin={{ top: 4, right: 8, bottom: 4, left: -16 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tick={TICK} tickLine={false} axisLine={false} />
              <YAxis tick={TICK} tickLine={false} axisLine={false} />
              <Tooltip {...TOOLTIP_STYLE} />
              <Bar dataKey="count" name="CFPs closing" fill={RED} radius={[4, 4, 0, 0]} maxBarSize={48} />
            </BarChart>
          </ChartCard>

          <ChartCard title="Where conferences are" sub="Top locations in view" wide>
            <BarChart
              data={q.data.by_country.map((r) => ({
                ...r,
                country: pretty(String(r.country)),
              }))}
              layout="vertical"
              margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
              <XAxis type="number" tick={TICK} tickLine={false} axisLine={false} />
              <YAxis
                dataKey="country"
                type="category"
                tick={TICK}
                tickLine={false}
                axisLine={false}
                width={72}
              />
              <Tooltip {...TOOLTIP_STYLE} />
              <Bar dataKey="count" name="Conferences" fill={INDIGO} radius={[0, 4, 4, 0]} maxBarSize={18} />
            </BarChart>
          </ChartCard>

          <SparseAwareCard
            title="Talks library"
            sub="Review pipeline and submission outcomes"
            points={[
              ...q.data.talks.by_review_status.map((r) => ({
                label: pretty(String(r.status)),
                count: Number(r.count),
              })),
              ...q.data.talks.submissions_by_outcome.map((r) => ({
                label: `Submitted: ${pretty(String(r.outcome))}`,
                count: Number(r.count),
              })),
            ]}
            emptyText="No talks in the library yet."
            barName="Talks"
            fill={INDIGO}
          />


          <ChartCard
            title="Spend & leads by month"
            sub={
              hasOutcomes
                ? "Outcomes of attended conferences"
                : "Flat at zero until attendance outcomes are recorded — mark people as attended and fill in \u201cHow it went\u201d."
            }
            wide
          >
            <LineChart
              data={q.data.outcomes_by_month}
              margin={{ top: 4, right: 8, bottom: 4, left: -8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tick={TICK} tickLine={false} axisLine={false} />
              <YAxis yAxisId="spend" tick={TICK} tickLine={false} axisLine={false} />
              <YAxis
                yAxisId="leads"
                orientation="right"
                tick={TICK}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip {...TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 13, color: "#d4d4d8" }} />
              <Line
                yAxisId="spend"
                type="monotone"
                dataKey="spend_usd"
                name="Spend (USD)"
                stroke={RED}
                strokeWidth={2}
                dot={false}
              />
              <Line
                yAxisId="leads"
                type="monotone"
                dataKey="leads"
                name="Leads"
                stroke={INDIGO}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ChartCard>

          {q.data.activity_mix.length > 0 ? (
            <ChartCard title="Activity mix" sub="What the team does at events">
              <BarChart
                data={q.data.activity_mix.map((r) => ({
                  ...r,
                  activity: pretty(String(r.activity)),
                }))}
                margin={{ top: 4, right: 8, bottom: 4, left: -16 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                <XAxis dataKey="activity" tick={TICK} tickLine={false} axisLine={false} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip {...TOOLTIP_STYLE} />
                <Bar dataKey="count" name="People" fill={RED} radius={[4, 4, 0, 0]} maxBarSize={48} />
              </BarChart>
            </ChartCard>
          ) : null}

          <SparseAwareCard
            title="Events per team member"
            sub={`${q.data.smes.with_expertise} of ${q.data.smes.active_total} SMEs have expertise described · guests included`}
            points={q.data.smes.events_per_sme.map((r) => ({
              label: r.on_roster === false ? `${String(r.name)} (guest)` : String(r.name),
              count: Number(r.events),
            }))}
            emptyText="No participation recorded yet."
            barName="Events"
            fill={RED}
            horizontal
          />

          {q.data.pillar_alignment.length > 0 ? (
            <ChartCard
              title="Pillar alignment"
              sub="How many conferences match each pillar BEST — hover for avg score and total aligned"
              wide
            >
              <BarChart
                data={q.data.pillar_alignment.map((r) => ({
                  ...r,
                  avg_score_100: Math.round(Number(r.avg_score) * 100),
                }))}
                margin={{ top: 4, right: 8, bottom: 4, left: -16 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                <XAxis dataKey="pillar" tick={TICK} tickLine={false} axisLine={false} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip {...TOOLTIP_STYLE} />
                <Bar dataKey="top_count" name="Best-match conferences" fill={INDIGO} radius={[4, 4, 0, 0]} maxBarSize={72} />
                <Bar dataKey="conferences" name="Total aligned" hide />
                <Bar dataKey="avg_score_100" name="Avg alignment (0-100)" hide />
              </BarChart>
            </ChartCard>
          ) : null}
        </div>
      )}
    </div>
  );
}

function SparseAwareCard({
  title,
  sub,
  points,
  emptyText,
  barName,
  fill,
  horizontal,
}: {
  title: string;
  sub?: string;
  points: { label: string; count: number }[];
  emptyText: string;
  barName: string;
  fill: string;
  horizontal?: boolean;
}) {
  if (points.length > 0) {
    return (
      <ChartCard title={title} sub={sub}>
        <BarChart
          data={points}
          layout={horizontal ? "vertical" : "horizontal"}
          margin={{ top: 4, right: 16, bottom: 4, left: horizontal ? 8 : -16 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={!horizontal} horizontal={!!horizontal === false} />
          {horizontal ? (
            <>
              <XAxis type="number" tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} />
              <YAxis dataKey="label" type="category" tick={TICK} tickLine={false} axisLine={false} width={110} />
            </>
          ) : (
            <>
              <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={false} />
              <YAxis tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} />
            </>
          )}
          <Tooltip {...TOOLTIP_STYLE} />
          <Bar dataKey="count" name={barName} fill={fill} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={horizontal ? 18 : 48} />
        </BarChart>
      </ChartCard>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {sub ? <p className="mt-0.5 text-xs text-fg-muted">{sub}</p> : null}
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3 pt-0">
        {points.length === 0 ? (
          <p className="text-sm text-fg-muted">{emptyText}</p>
        ) : (
          points.map((p) => <Sig key={p.label} label={p.label} value={p.count} />)
        )}
      </CardContent>
    </Card>
  );
}

function Sig({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex min-w-32 flex-col gap-0.5 rounded-lg border border-border-subtle bg-surface-2 px-4 py-2.5">
      <p className="text-xs text-fg-muted">{label}</p>
      <p className="text-xl font-bold tabular-nums">{value}</p>
    </div>
  );
}

function ChartCard({
  title,
  sub,
  wide,
  children,
}: {
  title: string;
  sub?: string;
  wide?: boolean;
  children: React.ReactElement;
}) {
  return (
    <Card className={wide ? "lg:col-span-2 xl:col-span-2" : ""}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {sub ? <p className="mt-0.5 text-xs text-fg-muted">{sub}</p> : null}
      </CardHeader>
      <CardContent className="pt-0">
        <div className="h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            {children}
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
