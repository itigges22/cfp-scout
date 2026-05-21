import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/conferences")({
  component: ConferencesPage,
});

function ConferencesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Conferences"
        description="Full list. Filter by status, pillar, audience, region."
      />
      <Card>
        <CardHeader>
          <CardTitle>All conferences</CardTitle>
          <CardDescription>
            Discovered, needs review, approved, rejected — everything Scout has seen.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState message="Wired up in plan 20 (dashboard & review UI)." />
        </CardContent>
      </Card>
    </div>
  );
}
