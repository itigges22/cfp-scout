import { createFileRoute } from "@tanstack/react-router";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Sources, topic review, series detection, workbook import/export."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SettingsLink
          title="Sources"
          description="Crawl targets (RSS / sitemap / page / ICS / wikicfp). Plan 14."
        />
        <SettingsLink
          title="Topic review"
          description="LLM-discovered topics pending admin approval. Plan 15."
        />
        <SettingsLink
          title="Conference series"
          description="Year-over-year linkage suggestions. Plan 23."
        />
        <SettingsLink
          title="Import / Export workbook"
          description="Round-trip the team's reference data via XLSX. Plan 31."
        />
        <SettingsLink
          title="Past conferences"
          description="Single-row + CSV import. Plan 09."
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Where do model thresholds + weights live?</CardTitle>
          <CardDescription>
            They're environment variables (MATCH_M_GATE, MATCH_W_*, DECAY_ENABLED, ...) in <code>.env</code>.
            Edit and run <code>make down &amp;&amp; make up</code>. There is no UI for them — tuning happens
            5 times in the app's life, not weekly, so a settings page would be over-engineering. See
            <code> docs/ops/secrets.md</code> for the rotation playbook.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}

function SettingsLink({ title, description }: { title: string; description: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
    </Card>
  );
}
