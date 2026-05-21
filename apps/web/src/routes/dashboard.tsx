import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/dashboard")({
  component: DashboardPage,
});

function DashboardPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dashboard"
        description="Upcoming conferences, pending reviews, CFP windows."
      />

      {/* Stat-card grid — populated by /api/v1/diagnostics + conferences listing (plan 20) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCardPlaceholder title="Upcoming approved" hint="next 90 days" />
        <StatCardPlaceholder title="Pending review" hint="needs your attention" />
        <StatCardPlaceholder title="CFP closing" hint="within 30 days" />
        <StatCardPlaceholder title="Low-coverage SMEs" hint="missing topics or audiences" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ranked conferences</CardTitle>
          <CardDescription>
            Sorted by overall fit score · drill into a row to see matcher rationale + recommended SMEs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState message="No conferences yet. Plan 14 wires up the scraper; once it runs, ranked results land here." />
        </CardContent>
      </Card>
    </div>
  );
}

// ---- shared local components ---------------------------------------------

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

function StatCardPlaceholder({ title, hint }: { title: string; hint: string }) {
  return (
    <Card>
      <CardHeader className="p-4">
        <CardDescription className="text-xs uppercase tracking-wider">{title}</CardDescription>
        <CardTitle className="text-3xl font-semibold tabular-nums">—</CardTitle>
      </CardHeader>
      <CardContent className="p-4 pt-0 text-xs text-fg-subtle">{hint}</CardContent>
    </Card>
  );
}
