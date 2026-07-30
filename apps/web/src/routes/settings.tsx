import { useMutation } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  Activity,
  BookOpen,
  Sliders,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

const NAV_LINKS = [
  {
    to: "/settings/tutorial",
    Icon: BookOpen,
    title: "Tutorial & docs",
    description: "End-to-end guide: matching pipeline, pillars, SME ranking, score boosts, tunables.",
  },
  {
    to: "/settings/tunables",
    Icon: Sliders,
    title: "Tunables & API keys",
    description: "Matcher gates, scoring weights, decay, scraper politeness, LLM API key.",
  },
  {
    to: "/diagnostics",
    Icon: Activity,
    title: "Diagnostics",
    description: "Live health snapshot: jobs, scraper, LLM activity, data freshness.",
  },
] as const;

function SettingsPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Settings"
        description="Admin control center — tunables, data import, and system actions."
      />

      {/* ── Quick-nav tiles ── */}
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted">Pages</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {NAV_LINKS.map(({ to, Icon, title, description }) => (
            <Link key={to} to={to} className="group block">
              <div className="flex h-full gap-4 rounded-xl border border-border bg-surface p-4 transition-colors group-hover:border-border-strong group-hover:bg-surface-2">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2 text-accent group-hover:bg-surface-3">
                  <Icon className="size-4" />
                </div>
                <div className="min-w-0">
                  <p className="font-semibold leading-snug">{title}</p>
                  <p className="mt-0.5 text-sm text-fg-muted">{description}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── Maintenance actions ── */}
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted">Maintenance</h2>
        <MaintenanceCard />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Maintenance — buttons for one-shot operator actions that don't have a
// natural home elsewhere (rescore, backfill, etc).
// ---------------------------------------------------------------------------
function MaintenanceCard() {
  const [result, setResult] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const rescoreMut = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/v1/admin/matcher/recompute-all", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as { queued_job_id?: string; algorithm_version?: string };
    },
    onSuccess: (data) =>
      setResult({
        kind: "success",
        text: `Rescore queued (job ${data.queued_job_id}). Runs in the background — check /diagnostics for progress, then refresh /dashboard once it settles.`,
      }),
    onError: (err) =>
      setResult({ kind: "error", text: `Rescore failed: ${(err as Error).message}` }),
  });

  const geocodeMut = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/v1/admin/discovery/geocode-backfill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as { attempted: number; resolved: number; skipped: number };
    },
    onSuccess: (data) =>
      setResult({
        kind: "success",
        text: `Geocoded ${data.resolved}/${data.attempted} conferences (${data.skipped} skipped). Map should refresh on next dashboard load.`,
      }),
    onError: (err) =>
      setResult({ kind: "error", text: `Geocode failed: ${(err as Error).message}` }),
  });

  const actions = [
    {
      label: "Rescore everything",
      pendingLabel: "Queuing…",
      variant: "default" as const,
      note: "Fires recompute_all_matches — one run per non-quarantined conference. Async, ~1–2 min.",
      isPending: rescoreMut.isPending,
      onClick: () => rescoreMut.mutate(),
    },
    {
      label: "Backfill missing coordinates",
      pendingLabel: "Geocoding…",
      variant: "outline" as const,
      note: "Resolves city → lat/lng for conferences without coordinates. Rate-limited, ~1 min per 60 rows.",
      isPending: geocodeMut.isPending,
      onClick: () => geocodeMut.mutate(),
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Maintenance</CardTitle>
        <CardDescription>
          One-shot operator actions. Imports auto-trigger a rescore — only use these when scoring drifts after a manual change.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {actions.map((a) => (
          <div key={a.label} className="flex items-start gap-4 rounded-lg border border-border bg-surface-2 p-4">
            <div className="flex-1">
              <p className="font-medium">{a.label}</p>
              <p className="mt-0.5 text-sm text-fg-muted">{a.note}</p>
            </div>
            <Button variant={a.variant} onClick={a.onClick} disabled={a.isPending} className="shrink-0">
              {a.isPending ? a.pendingLabel : a.label}
            </Button>
          </div>
        ))}
        {result && (
          <div
            className={[
              "rounded-lg border p-3 text-sm",
              result.kind === "success"
                ? "border-success/40 bg-success/10 text-success"
                : "border-danger/40 bg-danger/10 text-danger",
            ].join(" ")}
          >
            {result.text}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
