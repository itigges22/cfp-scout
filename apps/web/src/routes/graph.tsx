import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/graph")({
  component: GraphPage,
});

function GraphPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Graph"
        description="Obsidian-style exploration of conferences, topics, audiences, SMEs, pillars."
      />
      <Card>
        <CardHeader>
          <CardTitle>Network view</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState message="React Flow + filters land in plan 21. Capped at 500 nodes; truncation banner when filters return more." />
        </CardContent>
      </Card>
    </div>
  );
}
