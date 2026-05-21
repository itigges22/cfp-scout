import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

// Conference detail page. URL: /conferences/<uuid>
// Real implementation in plan 20; for plan 08 we just render the shell.

export const Route = createFileRoute("/conferences/$id")({
  component: ConferenceDetailPage,
});

function ConferenceDetailPage() {
  const { id } = Route.useParams();
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Conference detail"
        description={`Showing ${id}. Rationale, score breakdown, recommended SMEs, CFP timeline.`}
      />
      <Card>
        <CardHeader>
          <CardTitle>Detail panels land in plan 20</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState message="Score panel, rationale, recommended SMEs, CFP deadlines, neighborhood graph, decision actions." />
        </CardContent>
      </Card>
    </div>
  );
}
