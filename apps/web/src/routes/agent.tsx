import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/agent")({
  component: AgentPage,
});

function AgentPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Agent"
        description="Ask Scout about specific decisions. RAG-backed; cites sources; no autonomous actions."
      />
      <Card>
        <CardHeader>
          <CardTitle>Chat with the agent</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState message="Chat panel lands in plan 22. Slash commands: /explain conf:<id>, /recommend audience:<id>, /draft cfp:<id>." />
        </CardContent>
      </Card>
    </div>
  );
}
