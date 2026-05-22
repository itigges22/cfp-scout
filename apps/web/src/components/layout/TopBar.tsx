/**
 * Top bar with env badge, cost meter, and notification bell (plan 24).
 *
 * The bell shows the unread count for `cfp_digest` notifications and
 * opens a dropdown rendering the latest digest grouped by close-window
 * bucket. Each entry links to the conference detail page; a
 * copy-to-clipboard button serializes the digest as Markdown for paste
 * into Slack / email.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Bell, DollarSign } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, notificationsApi } from "@/lib/api";
import type {
  CfpDigestEntry,
  CfpDigestPayload,
  NotificationRead,
} from "@/lib/api-types";

export function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-6">
      <div className="flex items-center gap-3">
        <EnvBadge />
      </div>

      <div className="flex items-center gap-2">
        <CostMeter />
        <NotificationBell />
      </div>
    </header>
  );
}

function EnvBadge() {
  const env = import.meta.env.DEV ? "dev" : "prod";
  return (
    <span
      className="rounded-md border border-border-strong bg-surface-2 px-2 py-0.5 text-xs font-medium uppercase tracking-wider text-fg-muted"
      aria-label={`environment: ${env}`}
    >
      {env}
    </span>
  );
}

function CostMeter() {
  // Real value lands with plan 26's /diagnostics aggregator.
  return (
    <span className="flex items-center gap-1 rounded-md bg-surface-2 px-2 py-1 text-xs text-fg-muted">
      <DollarSign className="size-3" />
      <span aria-label="month-to-date LLM spend">$0.00 mtd</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Bell + dropdown
// ---------------------------------------------------------------------------
function NotificationBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const countQ = useQuery({
    queryKey: ["notifications", "unread", "cfp_digest"],
    queryFn: () => notificationsApi.unreadCount("cfp_digest"),
    // Poll while mounted so the badge tracks the daily 09:00 cron without
    // needing a websocket.
    refetchInterval: 60_000,
  });

  const latestQ = useQuery({
    queryKey: ["notifications", "latest", "cfp_digest"],
    queryFn: () => notificationsApi.latest("cfp_digest").catch(() => null),
    enabled: open,
  });

  const dismissMut = useMutation({
    mutationFn: (id: string) => notificationsApi.dismiss(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["notifications", "unread", "cfp_digest"],
      });
    },
  });

  const count = countQ.data?.count ?? 0;

  return (
    <div ref={rootRef} className="relative">
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Notifications${count ? ` (${count} unread)` : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell className="size-4" />
        {count > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg">
            {count > 9 ? "9+" : count}
          </span>
        ) : null}
      </Button>
      {open ? (
        <DigestDropdown
          latest={latestQ.data ?? null}
          loading={latestQ.isLoading}
          onDismiss={(id) => dismissMut.mutate(id)}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dropdown panel
// ---------------------------------------------------------------------------
function DigestDropdown({
  latest,
  loading,
  onDismiss,
  onClose,
}: {
  latest: NotificationRead | null;
  loading: boolean;
  onDismiss: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-label="Notifications"
      className="absolute right-0 top-full z-50 mt-2 w-[420px] max-w-[92vw] rounded-lg border border-border bg-surface-1 shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
        <span className="text-xs uppercase tracking-wider text-fg-subtle">
          CFP digest
        </span>
        <div className="flex items-center gap-1">
          {latest ? (
            <>
              <CopyMarkdownButton />
              {!latest.seen ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDismiss(latest.id)}
                >
                  Dismiss
                </Button>
              ) : null}
            </>
          ) : null}
          <Button variant="ghost" size="sm" onClick={onClose}>
            ×
          </Button>
        </div>
      </div>
      <div className="max-h-[60vh] overflow-y-auto p-3">
        {loading ? (
          <p className="px-1 py-4 text-xs text-fg-muted">Loading…</p>
        ) : !latest ? (
          <EmptyState />
        ) : (
          <DigestBody payload={latest.payload as unknown as CfpDigestPayload} />
        )}
      </div>
      {latest ? (
        <p className="border-t border-border-subtle px-4 py-2 text-[10px] text-fg-subtle">
          Generated{" "}
          {new Date(
            (latest.payload as unknown as CfpDigestPayload).generated_at ??
              latest.created_at,
          ).toLocaleString()}
        </p>
      ) : null}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-2 px-3 py-8 text-center">
      <p className="text-sm text-fg-muted">No CFPs closing in the next 30 days.</p>
      <p className="text-xs text-fg-subtle">
        The daily 09:00 digest will populate this when conferences land.
      </p>
    </div>
  );
}

const BUCKET_TITLES: Record<string, string> = {
  "0_7": "Closing this week (0-7 days)",
  "8_14": "Closing next week (8-14 days)",
  "15_30": "Closing this month (15-30 days)",
};

function DigestBody({ payload }: { payload: CfpDigestPayload }) {
  const buckets = ["0_7", "8_14", "15_30"] as const;
  const total = buckets.reduce(
    (acc, k) => acc + (payload.buckets?.[k]?.length ?? 0),
    0,
  );
  if (total === 0) {
    return <EmptyState />;
  }
  return (
    <div className="flex flex-col gap-4">
      {buckets.map((key) => {
        const entries = payload.buckets?.[key] ?? [];
        if (entries.length === 0) return null;
        return (
          <section key={key}>
            <h4 className="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-wider text-fg-subtle">
              {BUCKET_TITLES[key]}
            </h4>
            <ul className="flex flex-col gap-1">
              {entries.map((e) => (
                <DigestEntryRow
                  key={`${e.conference_id}-${e.deadline_date}-${e.deadline_kind}`}
                  e={e}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function DigestEntryRow({ e }: { e: CfpDigestEntry }) {
  const scoreOutOf100 =
    e.overall_score !== null ? Math.round(e.overall_score * 100) : null;
  const kindLabel = e.deadline_kind.replace(/_/g, " ");
  return (
    <li>
      <Link
        to="/conferences/$id"
        params={{ id: e.conference_id }}
        className="block rounded-md px-2 py-2 hover:bg-surface-2"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{e.name}</p>
            <p className="text-[11px] text-fg-muted">
              <span className="capitalize">{kindLabel}</span> closes{" "}
              <span className="tabular-nums">{e.deadline_date}</span>{" "}
              <span className="text-fg-subtle">
                ({e.days_until} day{e.days_until === 1 ? "" : "s"})
              </span>
              {e.top_sme_name ? ` · suggested: ${e.top_sme_name}` : ""}
            </p>
          </div>
          {scoreOutOf100 !== null ? (
            <div className="flex shrink-0 items-baseline gap-1 tabular-nums">
              <span className="text-sm font-semibold">{scoreOutOf100}</span>
              <span className="text-[10px] text-fg-subtle">/100</span>
            </div>
          ) : null}
        </div>
      </Link>
    </li>
  );
}

function CopyMarkdownButton() {
  const [state, setState] = useState<"idle" | "copying" | "copied" | "error">(
    "idle",
  );
  const copy = async () => {
    setState("copying");
    try {
      const res = await notificationsApi.cfpDigestMarkdown();
      await navigator.clipboard.writeText(res.markdown);
      setState("copied");
      setTimeout(() => setState("idle"), 1500);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.problem.detail ?? err.problem.title
          : String(err);
      console.error("copy markdown failed:", msg);
      setState("error");
      setTimeout(() => setState("idle"), 2000);
    }
  };
  return (
    <Button variant="ghost" size="sm" onClick={copy} disabled={state === "copying"}>
      {state === "copying"
        ? "…"
        : state === "copied"
          ? "Copied!"
          : state === "error"
            ? "Error"
            : "Copy MD"}
    </Button>
  );
}
