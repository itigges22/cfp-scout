import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/smes")({
  component: SmesPage,
});

function SmesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="SMEs"
        description="team and Non-team subject-matter experts. Profiles drive the matcher."
      />
      <Card>
        <CardHeader>
          <CardTitle>SME directory</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState message="Profile cards + wizard land in plan 09. Bulk seed via the XLSX workbook in plan 31." />
        </CardContent>
      </Card>
    </div>
  );
}
