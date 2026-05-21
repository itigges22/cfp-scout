import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/audiences")({
  component: AudiencesPage,
});

function AudiencesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audiences"
        description="<vendor> personas. Defined by the team; used by the matcher's Stage A + SME ranker."
      />
      <Card>
        <CardHeader>
          <CardTitle>Audience profiles</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState message="Wizard lands in plan 09 (structured-entry: industry, role_seniority, pain points, key messages, exclusion criteria)." />
        </CardContent>
      </Card>
    </div>
  );
}
