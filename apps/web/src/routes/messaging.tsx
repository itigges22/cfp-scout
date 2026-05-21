import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/messaging")({
  component: MessagingPage,
});

function MessagingPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Messaging & positioning"
        description="The team's elevator pitch, themes, talking points. Drives the matcher's Stage A."
      />
      <Card>
        <CardHeader>
          <CardTitle>Messaging documents</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState message="Multi-step wizard lands in plan 09. PDF upload path in plan 12 (Docling)." />
        </CardContent>
      </Card>
    </div>
  );
}
