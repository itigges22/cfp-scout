import { Link, createFileRoute } from "@tanstack/react-router";

import {
  Card,
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
          to="/topics"
          title="Topic review"
          description="LLM-discovered topics pending admin approval. Approve to add to the active vocabulary; reject to deactivate. Plan 15 populates the queue."
        />
        <SettingsLink
          to="/past-conferences"
          title="Past conferences"
          description="History of who attended what. Powers the past-attendance signal in the SME matcher. Manual entry + CSV import (next pass)."
        />
        <SettingsLink
          to="/settings"
          title="Sources"
          description="Crawl targets (RSS / sitemap / page / ICS / wikicfp). UI lands in plan 14."
          disabled
        />
        <SettingsLink
          to="/settings"
          title="Conference series"
          description="Year-over-year linkage suggestions. UI lands in plan 23."
          disabled
        />
        <SettingsLink
          to="/settings"
          title="Import / Export workbook"
          description="Round-trip the team's reference data via XLSX. UI lands in plan 31."
          disabled
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

function SettingsLink({
  to,
  title,
  description,
  disabled,
}: {
  to: string;
  title: string;
  description: string;
  disabled?: boolean;
}) {
  const card = (
    <Card
      className={
        disabled
          ? "opacity-50"
          : "transition-colors hover:border-border-strong hover:bg-surface-2"
      }
    >
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
    </Card>
  );
  if (disabled) return card;
  return (
    <Link to={to} className="block">
      {card}
    </Link>
  );
}
