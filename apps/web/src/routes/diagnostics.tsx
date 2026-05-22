/**
 * /diagnostics — operational dashboard (plan 26).
 *
 * Six panels backed by a single denormalized GET /api/v1/diagnostics call
 * (30s server-side cache). Optional 30s auto-refresh, manual refresh
 * button, per-job retry buttons.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, diagnosticsApi } from "@/lib/api";
import type { DiagnosticsResponse } from "@/lib/api-types";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/diagnostics")({
  component: DiagnosticsPage,
});

function DiagnosticsPage() {
  const [autoRefresh, setAutoRefresh] = useState(true);
  const queryClient = useQueryClient();

  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => diagnosticsApi.get(),
    refetchInterval: autoRefresh ? 30_000 : false,
  });

  const refreshMut = useMutation({
    mutationFn: () => diagnosticsApi.refresh(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["diagnostics"] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader
          title="Diagnostics"
          description="LLM spend, jobs, scraper, data, digest, system."
        />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Diagnostics" description="Could not load diagnostics." />
        <Card>
          <CardContent className="py-6 text-sm text-danger">
            {error instanceof ApiError
              ? error.problem.detail ?? error.problem.title
              : String(error)}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Diagnostics"
        description="LLM spend, jobs, scraper, data, digest, system. 30s server cache."
      />

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-fg-subtle">
          Generated {new Date(data.generated_at).toLocaleString()}
          {isFetching ? " · refreshing…" : ""}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={() => refreshMut.mutate()}
          disabled={refreshMut.isPending}
        >
          {refreshMut.isPending ? "Refreshing…" : "Force refresh"}
        </Button>
        <label className="flex items-center gap-2 rounded-md border border-border bg-surface-2 px-3 py-1 text-xs">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          Auto-refresh (30s)
        </label>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <LlmPanel d={data} />
        <JobsPanel
          d={data}
          onRetry={(id) => {
            diagnosticsApi
              .retryJob(id)
              .then(() => {
                void refetch();
              })
              .catch((err) => {
                console.error("retry failed:", err);
              });
          }}
        />
        <ScraperPanel d={data} />
        <DataPanel d={data} />
        <DigestPanel d={data} />
        <SystemPanel d={data} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------
function LlmPanel({ d }: { d: DiagnosticsResponse }) {
  const llm = d.llm;
  const budget = llm.budget;
  const pct =
    budget.pct_used != null ? Math.min(1, Math.max(0, budget.pct_used)) : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid grid-cols-3 gap-2 text-xs">
          <Metric label="Calls (mtd)" value={llm.month_to_date.calls.toString()} />
          <Metric
            label="Tokens (mtd)"
            value={llm.month_to_date.tokens.toLocaleString()}
          />
          <Metric
            label="$ mtd"
            value={`$${llm.month_to_date.cost_usd.toFixed(4)}`}
          />
        </div>
        {budget.limit_usd ? (
          <div>
            <div className="mb-1 flex items-baseline justify-between text-xs">
              <span className="text-fg-muted">
                Budget ${budget.spent_usd.toFixed(2)} / ${budget.limit_usd.toFixed(2)}
              </span>
              <span
                className={
                  budget.threshold_warn ? "font-medium text-warning" : "text-fg-subtle"
                }
              >
                {pct != null ? `${Math.round(pct * 100)}% used` : "—"}
              </span>
            </div>
            <Progress value={pct ?? 0} />
          </div>
        ) : null}

        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            Last 24h by purpose
          </p>
          {llm.by_purpose_24h.length === 0 ? (
            <p className="text-xs text-fg-muted">No calls yet.</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {llm.by_purpose_24h.slice(0, 8).map((p) => (
                <li
                  key={p.purpose}
                  className="flex items-baseline justify-between gap-2 tabular-nums"
                >
                  <span className="truncate text-fg-muted">{p.purpose}</span>
                  <span className="text-fg">
                    {p.calls} · {p.tokens.toLocaleString()}t · ${p.cost_usd.toFixed(4)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {llm.recent_errors.length > 0 ? (
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
              Recent errors
            </p>
            <ul className="space-y-1 text-xs text-danger">
              {llm.recent_errors.map((e, i) => (
                <li key={i} className="truncate">
                  {e.at ? new Date(e.at).toLocaleString() : "?"} · {e.purpose}: {e.error}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function JobsPanel({
  d,
  onRetry,
}: {
  d: DiagnosticsResponse;
  onRetry: (job_id: string) => void;
}) {
  const j = d.jobs;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Jobs</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            Running ({j.running.length})
          </p>
          {j.running.length === 0 ? (
            <p className="text-xs text-fg-muted">None.</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {j.running.map((r) => (
                <li key={r.id} className="flex items-baseline justify-between gap-2">
                  <span className="text-fg-muted">{r.kind}</span>
                  <span className="text-fg-subtle">
                    {r.elapsed_seconds}s elapsed
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            Failed (24h)
          </p>
          {j.failed_24h.length === 0 ? (
            <p className="text-xs text-fg-muted">Clean.</p>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {j.failed_24h.slice(0, 5).map((f) => (
                <li
                  key={f.id}
                  className="flex items-start justify-between gap-2"
                >
                  <div className="min-w-0 flex-1">
                    <span className="font-medium text-fg">{f.kind}</span>{" "}
                    <span className="text-fg-subtle">
                      {f.started_at
                        ? new Date(f.started_at).toLocaleString()
                        : ""}
                    </span>
                    <p className="truncate text-danger">{f.error_preview}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onRetry(f.id)}
                  >
                    Retry
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            Next cron fires
          </p>
          {j.next_fires.length === 0 ? (
            <p className="text-xs text-fg-muted">Scheduler idle.</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {j.next_fires.map((n) => (
                <li
                  key={n.id}
                  className="flex items-baseline justify-between gap-2"
                >
                  <span className="text-fg-muted">{n.id}</span>
                  <span className="text-fg-subtle tabular-nums">
                    {n.next_run_time
                      ? new Date(n.next_run_time).toLocaleString()
                      : "—"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ScraperPanel({ d }: { d: DiagnosticsResponse }) {
  const s = d.scraper;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scraper</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-4 text-xs text-fg-muted">
          <span>
            <span className="font-medium text-fg">{s.sources.length}</span> sources
          </span>
          <span>
            <span className="font-medium text-fg">{s.js_blocked_pages}</span> JS-blocked pages
          </span>
          <span>
            <span className="font-medium text-fg">{s.disabled_sources.length}</span> disabled
          </span>
        </div>
        {s.sources.length === 0 ? (
          <p className="text-xs text-fg-muted">No sources configured yet.</p>
        ) : (
          <ul className="space-y-1.5 text-xs">
            {s.sources.slice(0, 10).map((src) => (
              <li key={src.id} className="flex items-baseline justify-between gap-2">
                <div className="min-w-0 flex-1 truncate">
                  <span className="font-medium text-fg">{src.name}</span>{" "}
                  <Badge variant="muted">{src.kind}</Badge>
                  {!src.enabled ? (
                    <Badge variant="danger" className="ml-1">disabled</Badge>
                  ) : null}
                  {!src.robots_allowed ? (
                    <Badge variant="warning" className="ml-1">robots blocked</Badge>
                  ) : null}
                </div>
                <span className="shrink-0 text-fg-subtle tabular-nums">
                  {src.pages_fetched} pages ·{" "}
                  {src.last_crawled_at
                    ? new Date(src.last_crawled_at).toLocaleString()
                    : "never"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function DataPanel({ d }: { d: DiagnosticsResponse }) {
  const data = d.data;
  const totalConfs = Object.values(data.conferences_by_status).reduce(
    (a, b) => a + b,
    0,
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Data</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2 text-xs">
          <Pill label="Conferences" value={totalConfs.toString()} />
          {Object.entries(data.conferences_by_status).map(([status, n]) => (
            <Pill key={status} label={status} value={n.toString()} muted />
          ))}
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <Metric label="Active SMEs" value={data.smes.total_active.toString()} />
          <Metric
            label="SMEs missing topics"
            value={data.smes.no_topics.toString()}
            warn={data.smes.no_topics > 0}
          />
          <Metric
            label="Active audiences"
            value={data.audiences_active.toString()}
          />
          <Metric
            label="Active series"
            value={data.series.active_count.toString()}
          />
        </div>

        {data.pending_topics > 0 || data.series.unlinked_conferences > 0 ? (
          <div className="flex flex-wrap gap-2 text-xs">
            {data.pending_topics > 0 ? (
              <Link
                to="/topics"
                className="rounded-md border border-warning/40 bg-warning/15 px-2 py-1 text-warning hover:bg-warning/25"
              >
                {data.pending_topics} pending topic{data.pending_topics === 1 ? "" : "s"} →
              </Link>
            ) : null}
            {data.series.unlinked_conferences > 0 ? (
              <span className="rounded-md border border-border bg-surface-2 px-2 py-1 text-fg-muted">
                {data.series.unlinked_conferences} unlinked conference
                {data.series.unlinked_conferences === 1 ? "" : "s"} (see series suggestions)
              </span>
            ) : null}
          </div>
        ) : null}

        {data.embedding_model ? (
          <div className="text-xs text-fg-muted">
            Embedding model:{" "}
            <span className="text-fg">{data.embedding_model.name}</span> ·{" "}
            <span className="tabular-nums">{data.embedding_model.dimension}d</span>{" "}
            ({data.embedding_model.provider})
          </div>
        ) : null}

        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            Conference freshness (decay {data.decay_enabled ? "on" : "off"})
          </p>
          <FreshnessHistogram counts={data.freshness_histogram.counts} />
        </div>
      </CardContent>
    </Card>
  );
}

function FreshnessHistogram({ counts }: { counts: number[] }) {
  const max = Math.max(1, ...counts);
  return (
    <div className="flex h-12 items-end gap-0.5">
      {counts.map((n, i) => (
        <div
          key={i}
          className="flex-1 rounded-t bg-accent/60"
          style={{ height: `${(n / max) * 100}%` }}
          title={`bucket ${i}: ${n}`}
        />
      ))}
    </div>
  );
}

function DigestPanel({ d }: { d: DiagnosticsResponse }) {
  const latest = d.digest.latest;
  return (
    <Card>
      <CardHeader>
        <CardTitle>CFP digest</CardTitle>
      </CardHeader>
      <CardContent>
        {!latest ? (
          <p className="text-xs text-fg-muted">
            No digest yet — daily 09:00 cron will populate when CFPs land.
          </p>
        ) : (
          <div className="flex flex-col gap-2 text-xs">
            <div>
              Generated{" "}
              {new Date(latest.generated_at ?? latest.created_at).toLocaleString()}
            </div>
            <div className="flex flex-wrap gap-2">
              <Pill label="Total" value={latest.total_entries.toString()} />
              {Object.entries(latest.bucket_counts).map(([k, n]) => (
                <Pill key={k} label={k} value={n.toString()} muted />
              ))}
            </div>
            {latest.seen ? (
              <Badge variant="muted">seen</Badge>
            ) : (
              <Badge variant="success">unread</Badge>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SystemPanel({ d }: { d: DiagnosticsResponse }) {
  const s = d.system;
  return (
    <Card>
      <CardHeader>
        <CardTitle>System</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-xs">
        <Row k="Env" v={s.env} />
        <Row k="Uptime" v={formatUptime(s.uptime_seconds)} />
        <Row k="Postgres" v={shorten(s.postgres.version)} />
        <Row k="DB size" v={s.postgres.db_size_pretty} />
        <Row k="Storage path" v={s.storage_path} mono />
        {s.disk_usage ? (
          <div>
            <Row
              k="Disk"
              v={`${formatBytes(s.disk_usage.used_bytes)} / ${formatBytes(s.disk_usage.total_bytes)}`}
            />
            <Progress
              value={s.disk_usage.used_bytes / s.disk_usage.total_bytes}
              className="mt-1"
              size="sm"
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tiny presentational helpers
// ---------------------------------------------------------------------------
function Metric({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5">
      <p className="text-[10px] uppercase tracking-wider text-fg-subtle">
        {label}
      </p>
      <p
        className={`text-sm font-semibold tabular-nums ${warn ? "text-warning" : "text-fg"}`}
      >
        {value}
      </p>
    </div>
  );
}

function Pill({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <Badge variant={muted ? "muted" : "default"} className="tabular-nums">
      {label}: <span className="ml-1 font-semibold">{value}</span>
    </Badge>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-fg-subtle">{k}</span>
      <span className={`text-fg ${mono ? "font-mono text-[11px]" : ""}`}>{v}</span>
    </div>
  );
}

function formatUptime(seconds: number | null): string {
  if (seconds == null) return "?";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400)
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  for (const u of units) {
    if (v < 1024) return `${v.toFixed(1)} ${u}`;
    v /= 1024;
  }
  return `${v.toFixed(1)} PB`;
}

function shorten(s: string): string {
  // postgres version() returns a long string; grab "PostgreSQL X.Y" prefix.
  const m = s.match(/^(PostgreSQL\s+\d+\.\d+)/);
  return m ? m[1]! : s.slice(0, 60);
}
