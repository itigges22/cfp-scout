/**
 * /diagnostics — usage dashboard + system health.
 *
 * Above the fold: big usage stats with a time-window filter.
 * Below the fold: background system health panels.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, diagnosticsApi } from "@/lib/api";
import type { DiagnosticsResponse } from "@/lib/api-types";

export const Route = createFileRoute("/diagnostics")({
  component: DiagnosticsPage,
});

type Window = "7d" | "30d" | "all";
const WINDOWS: { key: Window; label: string }[] = [
  { key: "7d",  label: "7 days"  },
  { key: "30d", label: "30 days" },
  { key: "all", label: "All time" },
];

function DiagnosticsPage() {
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [window, setWindow] = useState<Window>("30d");
  const queryClient = useQueryClient();

  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => diagnosticsApi.get(),
    refetchInterval: autoRefresh ? 30_000 : false,
  });

  const refreshMut = useMutation({
    mutationFn: () => diagnosticsApi.refresh(),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["diagnostics"] }),
  });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6 p-6">
        <Skeleton className="h-12 w-64" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-36" />)}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-12 text-center">
        <p className="text-lg font-semibold text-danger">Could not load diagnostics</p>
        <p className="text-sm text-fg-muted">
          {error instanceof ApiError
            ? error.problem.detail ?? error.problem.title
            : String(error)}
        </p>
        <Button onClick={() => void refreshMut.mutate()}>Retry</Button>
      </div>
    );
  }

  const u = data.usage;
  const totalConfs = Object.values(u.conferences_by_status).reduce((a, b) => a + b, 0);
  const approved = u.conferences_by_status["approved"] ?? 0;
  const decisionCount = u.decisions[window];
  const outcomeBreakdown = u.decisions_by_outcome[window];

  return (
    <div className="flex flex-col">
      {/* ── Hero: Usage Dashboard ─────────────────────────────────────── */}
      <div className="flex flex-col gap-6 p-6 pb-8">

        {/* Title + controls row */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Diagnostics</h1>
            <p className="mt-0.5 text-sm text-fg-muted">
              App usage and system health
              {isFetching ? " · refreshing…" : ""}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Auto-refresh
            </label>
            <Button
              variant="outline"
              onClick={() => refreshMut.mutate()}
              disabled={refreshMut.isPending}
            >
              {refreshMut.isPending ? "Refreshing…" : "Force refresh"}
            </Button>
          </div>
        </div>

        {/* Time-window selector */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-fg-muted">Showing:</span>
          <div className="flex rounded-lg border border-border bg-surface-2 p-0.5">
            {WINDOWS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setWindow(key)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  window === key
                    ? "bg-accent text-accent-fg"
                    : "text-fg-muted hover:text-fg",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="text-sm text-fg-muted">
            · Generated {new Date(data.generated_at).toLocaleString()}
          </span>
        </div>

        {/* Big 4 stat cards (always all-time — these are current state) */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <HeroStat
            label="Conferences Approved"
            value={approved}
            sub={`${totalConfs} total across all statuses`}
            accent
          />
          <HeroStat
            label="Conferences Scored"
            value={u.conferences_scored}
            sub="have a match score"
          />
          <HeroStat
            label="Conferences Attended"
            value={u.conferences_attended}
            sub={`${u.conferences_attended_scored} with verdict`}
          />
          <HeroStat
            label="Talk Submissions"
            value={u.talk_submissions_total}
            sub="talks pitched to conferences"
          />
        </div>

        {/* Decision activity — filtered by window */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <HeroStat
            label={`Decisions (${window === "all" ? "all time" : window})`}
            value={decisionCount}
          />
          <div className="col-span-2 flex flex-col justify-center gap-3 rounded-xl border border-border bg-surface px-5 py-4">
            <p className="text-sm font-medium text-fg-muted">
              By outcome — {window === "all" ? "all time" : `last ${window}`}
            </p>
            {Object.keys(outcomeBreakdown).length === 0 ? (
              <p className="text-sm text-fg-muted">No decisions recorded in this window.</p>
            ) : (
              <div className="flex flex-wrap gap-6">
                {Object.entries(outcomeBreakdown).map(([outcome, n]) => (
                  <div key={outcome} className="flex flex-col">
                    <span className="text-3xl font-bold tabular-nums">{n}</span>
                    <span className="text-sm capitalize text-fg-muted">
                      {outcome.replace(/_/g, " ")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-col justify-center rounded-xl border border-border bg-surface px-5 py-4">
            <p className="text-sm font-medium text-fg-muted">Active SMEs</p>
            <p className="mt-1 text-3xl font-bold">{u.smes_active}</p>
          </div>
        </div>

        {/* CFP Digest — belongs in usage, not background systems */}
        <DigestPanel d={data} />
      </div>

      {/* ── Divider ───────────────────────────────────────────────────── */}
      <div className="border-t border-border" />

      {/* ── Background system panels ──────────────────────────────────── */}
      <div className="flex flex-col gap-6 p-6">
        <h2 className="text-lg font-semibold text-fg-muted">Background Systems</h2>

        <ErrorFeedPanel
          d={data}
          onRetry={(id) =>
            diagnosticsApi.retryJob(id).then(() => void refetch()).catch(console.error)
          }
        />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <LlmActivityPanel d={data} window={window} />
          <JobsPanel d={data} />
          <ScraperPanel d={data} />
          <DataPanel d={data} />
        </div>

        <SystemPanel d={data} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hero stat card
// ---------------------------------------------------------------------------
function HeroStat({
  label, value, sub, accent,
}: {
  label: string; value: number; sub?: string; accent?: boolean;
}) {
  return (
    <div className={cn(
      "flex flex-col justify-between rounded-xl border px-5 py-4",
      accent ? "border-accent/30 bg-accent/5" : "border-border bg-surface",
    )}>
      <p className="text-sm font-medium text-fg-muted">{label}</p>
      <p className={cn("mt-2 text-5xl font-bold tabular-nums", accent ? "text-accent" : "text-fg")}>
        {value.toLocaleString()}
      </p>
      {sub ? <p className="mt-1.5 text-sm text-fg-muted">{sub}</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CFP Digest
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Unified error feed — ONE terminal for everything that went wrong
// ---------------------------------------------------------------------------
// LLM call errors and failed background jobs used to live in two separate
// panels; checking "is anything broken?" meant reading both. This merges
// them into a single timestamped stream, newest first, in one terminal.
function ErrorFeedPanel({
  d,
  onRetry,
}: {
  d: DiagnosticsResponse;
  onRetry: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  // "Clear" hides LLM errors recorded up to now (history kept; new errors
  // still appear). It moved here from the old LLM Activity terminal when
  // the per-panel terminals were folded into this single feed.
  const clearErrorsMut = useMutation({
    mutationFn: diagnosticsApi.clearLlmErrors,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["diagnostics"] }),
  });

  const entries: { at: string | null; tag: string; text: string; jobId?: string }[] = [
    ...d.llm.recent_errors.map((e) => ({
      at: e.at,
      tag: "llm",
      text: `${e.purpose ?? "?"} · ${e.error}`,
    })),
    ...d.jobs.failed_24h.map((f) => ({
      at: f.started_at,
      tag: "job",
      text: `${f.kind} · ${f.error_preview ?? "failed"}`,
      jobId: f.id,
    })),
  ].sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="font-semibold">Error feed</h3>
        <div className="flex items-center gap-3">
          <span className="text-xs text-fg-muted">
            LLM errors + failed jobs, last 24h, newest first
          </span>
          {d.llm.recent_errors.length > 0 ? (
            <Button
              size="sm"
              variant="outline"
              disabled={clearErrorsMut.isPending}
              onClick={() => clearErrorsMut.mutate()}
              title="Hide LLM errors recorded up to now (history is kept; new errors still appear)"
            >
              {clearErrorsMut.isPending ? "Clearing…" : "Clear LLM errors"}
            </Button>
          ) : null}
        </div>
      </div>
      <TerminalBox>
        {entries.length === 0 ? (
          <span className="text-success">✓ no errors in the last 24 hours</span>
        ) : (
          entries.map((e, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              <span className="text-fg-subtle">
                {e.at ? new Date(e.at).toLocaleTimeString() : "--:--"}
              </span>{" "}
              <span className={e.tag === "llm" ? "text-warning" : "text-danger"}>
                [{e.tag}]
              </span>{" "}
              {e.text}
              {e.jobId ? (
                <>
                  {" "}
                  <button
                    className="text-accent underline hover:no-underline"
                    onClick={() => onRetry(e.jobId!)}
                  >
                    retry
                  </button>
                </>
              ) : null}
            </div>
          ))
        )}
      </TerminalBox>
    </div>
  );
}

function DigestPanel({ d }: { d: DiagnosticsResponse }) {
  const latest = d.digest.latest;
  if (!latest) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>CFP Digest</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-6">
        <div>
          <p className="text-sm text-fg-muted">Generated</p>
          <p className="mt-0.5 font-medium">
            {new Date(latest.generated_at ?? latest.created_at).toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-sm text-fg-muted">Total entries</p>
          <p className="mt-0.5 text-2xl font-bold tabular-nums">{latest.total_entries}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(latest.bucket_counts).map(([k, n]) => (
            <Badge key={k} variant="muted" className="tabular-nums">{k}: {n}</Badge>
          ))}
        </div>
        {latest.seen ? (
          <Badge variant="muted">Seen</Badge>
        ) : (
          <Badge variant="success">Unread</Badge>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// LLM Activity — window-aware
// ---------------------------------------------------------------------------
function LlmConnectivityStatus({ llm }: { llm: DiagnosticsResponse["llm"] }) {
  const conn = llm.connectivity;
  if (!conn) return null;
  const { endpoint, config } = conn;

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        {endpoint.ok ? (
          <Badge variant="success">Endpoint reachable · {endpoint.latency_ms}ms</Badge>
        ) : (
          <Badge variant="danger">Endpoint unreachable</Badge>
        )}
        {config.dry_run ? (
          <Badge variant="warning">DRY-RUN — no real LLM calls are being made</Badge>
        ) : null}
        <Badge variant="muted">
          key {config.api_key_masked ?? "not set"} ·{" "}
          {config.api_key_source === "db_override" ? "from DB" : "from env"}
        </Badge>
      </div>
      {!endpoint.ok && endpoint.error ? (
        <p className="text-sm text-danger">{endpoint.error}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={
            conn.chat_model_available === false
              ? "danger"
              : conn.chat_model_available
                ? "success"
                : "muted"
          }
        >
          chat: {config.chat_model}
          {conn.chat_model_available === false ? " — NOT on backend" : ""}
        </Badge>
        <Badge
          variant={
            conn.embedding_model_available === false
              ? "danger"
              : conn.embedding_model_available
                ? "success"
                : "muted"
          }
        >
          embed: {config.embedding_model}
          {conn.embedding_model_available === false ? " — NOT on backend" : ""}
        </Badge>
      </div>
      {(conn.chat_model_available === false || conn.embedding_model_available === false) &&
      endpoint.available_models ? (
        <p className="text-sm text-fg-muted">
          Backend serves: {endpoint.available_models.join(", ")}
        </p>
      ) : null}
      <p className="truncate text-xs text-fg-muted">{config.base_url}</p>
    </div>
  );
}

function LlmActivityPanel({ d, window }: { d: DiagnosticsResponse; window: Window }) {
  const llm = d.llm;
  // Map the page window to the corresponding call count key
  const windowCallKey = window === "7d" ? "7d" : window === "30d" ? "30d" : "all";
  const highlightedCalls = llm.calls[windowCallKey];

  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM Activity</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {/* Live connectivity — talks to the backend, unlike the call
            history below which can look healthy while dry-run swallows
            every call or a rotated key silently fails. */}
        <LlmConnectivityStatus llm={llm} />

        {/* Success signal: without this, healthy-but-idle and broken
            look identical. */}
        <div className="flex flex-wrap items-center gap-2">
          {llm.last_success ? (
            <Badge variant="success">
              last success:{" "}
              {llm.last_success.at ? new Date(llm.last_success.at).toLocaleString() : "?"} ·{" "}
              {llm.last_success.purpose}
              {llm.last_success.latency_ms != null ? ` · ${llm.last_success.latency_ms}ms` : ""}
            </Badge>
          ) : (
            <Badge variant="muted">no successful calls recorded yet</Badge>
          )}
          <Badge variant={llm.calls_24h_errors > 0 ? "warning" : "muted"} className="tabular-nums">
            24h: {llm.calls_24h_ok} ok / {llm.calls_24h_errors} errors
          </Badge>
        </div>

        {/* Window-highlighted count */}
        <div className="flex items-baseline gap-2">
          <span className="text-4xl font-bold tabular-nums">{highlightedCalls.toLocaleString()}</span>
          <span className="text-sm text-fg-muted">
            calls — {window === "all" ? "all time" : `last ${window}`}
          </span>
        </div>

        {/* All windows as secondary */}
        <div className="grid grid-cols-4 gap-2">
          {(["24h", "7d", "30d", "all"] as const).map((k) => (
            <div key={k} className="flex flex-col gap-0.5 rounded-lg border border-border bg-surface-2 px-3 py-2">
              <p className="text-sm text-fg-muted">{k === "all" ? "All time" : k}</p>
              <p className="text-lg font-semibold tabular-nums">{llm.calls[k].toLocaleString()}</p>
            </div>
          ))}
        </div>

        {llm.by_purpose_24h.length > 0 ? (
          <div>
            <p className="mb-2 text-sm font-medium text-fg-muted">By purpose (last 24h)</p>
            <ul className="space-y-1.5">
              {llm.by_purpose_24h.slice(0, 8).map((p) => (
                <li key={p.purpose} className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm text-fg-muted">{p.purpose}</span>
                  <span className="text-sm font-medium tabular-nums">{p.calls}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {/* Errors live in the unified Error feed above — one terminal,
            not one per panel. */}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------
const STALE_THRESHOLD_SECONDS = 60 * 60 * 4; // 4h — beyond this is likely a zombie

function JobsPanel({ d }: { d: DiagnosticsResponse }) {
  const j = d.jobs;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Jobs</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">

        {/* Running */}
        <div>
          <p className="mb-2 text-sm font-medium text-fg-muted">
            Running ({j.running.length})
          </p>
          {j.running.length === 0 ? (
            <p className="text-sm text-fg-muted">None.</p>
          ) : (
            <TerminalBox>
              {j.running.map((r, i) => {
                const stale = (r.elapsed_seconds ?? 0) > STALE_THRESHOLD_SECONDS;
                return (
                  <div
                    key={r.id}
                    className={cn(
                      "flex justify-between gap-4",
                      stale ? "text-warning" : "text-fg",
                    )}
                  >
                    <span>{r.kind}</span>
                    <span className="tabular-nums">
                      {formatElapsed(r.elapsed_seconds)}
                      {stale ? " ⚠ stale" : ""}
                    </span>
                    {i < j.running.length - 1 ? "\n" : ""}
                  </div>
                );
              })}
            </TerminalBox>
          )}
        </div>

        {/* Failed jobs live in the unified Error feed above, retry
            button included. */}

        {/* Next fires */}
        <div>
          <p className="mb-2 text-sm font-medium text-fg-muted">Next cron fires</p>
          {j.next_fires.length === 0 ? (
            <p className="text-sm text-fg-muted">Scheduler idle.</p>
          ) : (
            <ul className="space-y-1.5">
              {j.next_fires.map((n) => (
                <li key={n.id} className="flex items-center justify-between gap-2">
                  <span className="text-sm text-fg-muted">{n.id}</span>
                  <span className="text-sm tabular-nums">
                    {n.next_run_time ? new Date(n.next_run_time).toLocaleString() : "—"}
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

// ---------------------------------------------------------------------------
// Scraper
// ---------------------------------------------------------------------------
function ScraperPanel({ d }: { d: DiagnosticsResponse }) {
  const s = d.scraper;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scraper</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-6 text-sm">
          <span><span className="font-semibold">{s.sources.length}</span> <span className="text-fg-muted">sources</span></span>
          <span><span className="font-semibold">{s.js_blocked_pages}</span> <span className="text-fg-muted">JS-blocked</span></span>
          <span><span className="font-semibold">{s.disabled_sources.length}</span> <span className="text-fg-muted">disabled</span></span>
        </div>
        {s.sources.length === 0 ? (
          <p className="text-sm text-fg-muted">No sources configured yet.</p>
        ) : (
          <ul className="space-y-2">
            {s.sources.slice(0, 10).map((src) => (
              <li key={src.id} className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 flex-1 items-center gap-2 truncate">
                  <span className="font-medium">{src.name}</span>
                  <Badge variant="muted">{src.kind}</Badge>
                  {!src.enabled ? <Badge variant="danger">disabled</Badge> : null}
                  {!src.robots_allowed ? <Badge variant="warning">robots blocked</Badge> : null}
                </div>
                <span className="shrink-0 text-sm text-fg-muted tabular-nums">
                  {src.pages_fetched} pages · {src.last_crawled_at ? new Date(src.last_crawled_at).toLocaleString() : "never"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Data catalog
// ---------------------------------------------------------------------------
function DataPanel({ d }: { d: DiagnosticsResponse }) {
  const data = d.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Data Catalog</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <MiniStat label="Active SMEs" value={data.smes.total_active} />
          <MiniStat label="Active audiences" value={data.audiences_active} />
          <MiniStat label="Active series" value={data.series.active_count} />
        </div>

        {data.series.unlinked_conferences > 0 ? (
          <div className="flex flex-wrap gap-2">
            <span className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm text-fg-muted">
              {data.series.unlinked_conferences} unlinked conference{data.series.unlinked_conferences === 1 ? "" : "s"}
            </span>
          </div>
        ) : null}

        {data.embedding_model ? (
          <p className="text-sm text-fg-muted">
            Embedding: <span className="text-fg">{data.embedding_model.name}</span> · {data.embedding_model.dimension}d ({data.embedding_model.provider})
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------
function SystemPanel({ d }: { d: DiagnosticsResponse }) {
  const s = d.system;
  return (
    <Card>
      <CardHeader>
        <CardTitle>System</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <InfoRow k="Env" v={s.env} />
        <InfoRow k="Uptime" v={formatElapsed(s.uptime_seconds)} />
        <InfoRow k="Postgres" v={shorten(s.postgres.version)} />
        <InfoRow k="DB size" v={s.postgres.db_size_pretty} />
        <InfoRow k="Storage" v={s.storage_path} mono />
        {s.disk_usage ? (
          <div className="sm:col-span-2">
            <InfoRow
              k="Disk"
              v={`${formatBytes(s.disk_usage.used_bytes)} / ${formatBytes(s.disk_usage.total_bytes)}`}
            />
            <Progress value={s.disk_usage.used_bytes / s.disk_usage.total_bytes} size="sm" className="mt-1.5" />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Shared small components
// ---------------------------------------------------------------------------
function TerminalBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="max-h-52 overflow-y-auto rounded-md border border-border bg-canvas px-3 py-2.5 font-mono text-sm leading-relaxed">
      {children}
    </div>
  );
}

function MiniStat({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-surface-2 px-3 py-2.5">
      <p className="text-sm text-fg-muted">{label}</p>
      <p className={cn("text-xl font-bold tabular-nums", warn ? "text-warning" : "text-fg")}>
        {value.toLocaleString()}
      </p>
    </div>
  );
}

function InfoRow({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-sm text-fg-muted">{k}</span>
      <span className={cn("text-sm font-medium", mono && "break-all font-mono")}>{v}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
function formatElapsed(seconds: number | null): string {
  if (seconds == null) return "?";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
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
  const m = s.match(/^(PostgreSQL\s+\d+\.\d+)/);
  return m ? m[1]! : s.slice(0, 60);
}
