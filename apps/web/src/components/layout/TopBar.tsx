import { Bell, DollarSign } from "lucide-react";

import { Button } from "@/components/ui/button";

// The top bar. For plan 08 this is mostly a placeholder — the bell badge
// (plan 24) and the running LLM cost (plan 26) will wire to real data when
// those endpoints land.

export function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-6">
      <div className="flex items-center gap-3">
        <EnvBadge />
      </div>

      <div className="flex items-center gap-2">
        <CostMeter />
        <Button variant="ghost" size="icon" aria-label="Notifications">
          <Bell className="size-4" />
        </Button>
      </div>
    </header>
  );
}

function EnvBadge() {
  // Plan 26's /diagnostics endpoint exposes the current ENV; until then
  // we read from import.meta.env.
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
  // Real value comes from /api/v1/diagnostics (plan 26). Hardcoded placeholder
  // for the layout shell.
  return (
    <span className="flex items-center gap-1 rounded-md bg-surface-2 px-2 py-1 text-xs text-fg-muted">
      <DollarSign className="size-3" />
      <span aria-label="month-to-date LLM spend">$0.00 mtd</span>
    </span>
  );
}
