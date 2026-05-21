import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/diagnostics")({
  component: DiagnosticsPage,
});

function DiagnosticsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Diagnostics"
        description="LLM spend, job status, scraper health, data coverage. Plan 26."
      />
      <Card>
        <CardHeader>
          <CardTitle>System status</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState message="LLM panel, jobs panel, scraper panel, data panel, digest panel, system panel land in plan 26 once the aggregator endpoint exists." />
        </CardContent>
      </Card>
    </div>
  );
}
