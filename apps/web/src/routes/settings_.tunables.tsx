/**
 * /settings/tunables — single-page control panel for every runtime knob.
 *
 * Backend: GET / PATCH / DELETE /api/v1/admin/settings.
 * Surfaces the LLM API key (masked), matcher gates and weights, SME
 * ranker weights, team scoring weights, decay flag, scraper politeness,
 * and logging level. Each section has its own save button so unrelated
 * edits don't bundle. Restart-required keys show a yellow banner; values
 * not yet overridden render their env-default with a "default" pill.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageBanner, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/settings_/tunables")({
  component: TunablesPage,
});

type SettingSpec = {
  name: string;
  kind: "int" | "float" | "bool" | "str" | "secret" | "list_str";
  group: "llm" | "matcher" | "sme" | "team" | "decay" | "discovery" | "scraper" | "logging" | "talks" | "conferences";
  label: string;
  description: string;
  restart_required: boolean;
  min_value: number | null;
  max_value: number | null;
  enum_values: string[] | null;
};

type SettingItem = {
  spec: SettingSpec;
  value: unknown;
  masked: boolean;
  is_overridden: boolean;
  overridden_at: string | null;
  actor_label: string | null;
};

type SettingsListResponse = { items: SettingItem[] };

const GROUP_ORDER: SettingSpec["group"][] = [
  "llm",
  "matcher",
  "sme",
  "team",
  "decay",
  "discovery",
  "conferences",
  "talks",
  "scraper",
  "logging",
];

const GROUP_TITLE: Record<SettingSpec["group"], string> = {
  llm: "LLM API",
  matcher: "Matcher gates & weights",
  sme: "SME ranker weights",
  team: "Team recommendations",
  decay: "Decay",
  discovery: "Web discovery",
  conferences: "Conferences",
  talks: "Talks library",
  scraper: "Scraper",
  logging: "Logging",
};

const GROUP_NOTE: Partial<Record<SettingSpec["group"], string>> = {
  talks: "Controls the talks library reuse-detection system and the topic auto-approval filter. The flag threshold is the number of distinct conferences a talk must be applied to before it turns red and requires a confirmation step. The noise blocklist is a list of substrings (one per line) — any topic whose name contains one of these is silently dropped instead of being added to the vocabulary. Add logistics terms that keep slipping through.",
  llm: "The API key is masked after saving. To rotate it, paste the new value and save. Budget limit cuts off LLM calls for the billing period — set to 0 to disable the cap.",
  matcher: "Gates (M/P/S) are the minimum score a conference must reach before advancing to the next stage — below the gate it gets a 'needs review' status instead of 'approved'. Weights control how much each stage contributes to the final overall score; the pipeline normalizes them so they don't need to sum to 1.0.",
  sme: "The five dimensions that produce each SME's composite score. Must sum to exactly 1.0. Topic and bio are the strongest signals; location and past attendance are secondary nudges.",
  team: "Controls the multi-SME team recommendation engine that picks complementary groups of 1, 2, or 3 speakers per conference.",
  decay: "Applies a freshness penalty to older embedding chunks so stale conference descriptions influence scores less over time. Disable if you want raw cosine scores with no time weighting.",
  scraper: "Controls how aggressively the conference discovery scraper runs. Politeness delay limits how fast it hits external sites — lower values are faster but risk rate-limiting or bans.",
  logging: "Structured log level for the API process. 'info' is the production default. 'debug' logs every DB query and LLM prompt — very noisy but useful when diagnosing a specific issue.",
};

function TunablesPage() {
  const query = useQuery<SettingsListResponse>({
    queryKey: ["admin", "settings"],
    queryFn: async () => {
      const res = await fetch("/api/v1/admin/settings");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as SettingsListResponse;
    },
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Tunables & API keys"
        description="Adjust how the matcher, scraper, and LLM pipeline behave — no restart needed for most changes."
      />
      <PageBanner>
        Each section has its own <strong>Save</strong> button so unrelated edits don't bundle
        together. Values shown with a <em>default</em> pill are inherited from the environment
        and not yet overridden — saving a value locks it into the database and it will survive
        restarts. Settings marked <strong>⚠ restart required</strong> only take effect when
        the API container restarts. After changing gates or weights, go to{" "}
        <strong>Settings → Maintenance → Rescore everything</strong> to apply them.
      </PageBanner>
      <Link to="/settings" className="text-sm text-accent hover:underline">
        ← Back to settings
      </Link>

      {query.isLoading && <p className="text-sm text-fg-muted">Loading…</p>}
      {query.error && (
        <p className="text-sm text-danger">
          Failed to load: {String((query.error as Error).message)}
        </p>
      )}

      {query.data &&
        GROUP_ORDER.map((g) => (
          <GroupCard
            key={g}
            group={g}
            items={query.data.items.filter((i) => i.spec.group === g)}
          />
        ))}
    </div>
  );
}

function GroupCard({
  group,
  items,
}: {
  group: SettingSpec["group"];
  items: SettingItem[];
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const mutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      const res = await fetch("/api/v1/admin/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, actor_label: "ui_admin" }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (data as { detail?: string }).detail ?? `HTTP ${res.status}`,
        );
      }
      return (await res.json()) as { updated: string[] };
    },
    onSuccess: () => {
      setError(null);
      setDraft({});
      setSavedAt(Date.now());
      queryClient.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
    onError: (err) => setError(String((err as Error).message)),
  });

  const resetMut = useMutation({
    mutationFn: async (name: string) => {
      const res = await fetch(`/api/v1/admin/settings/${name}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "settings"] }),
  });

  const dirtyCount = Object.keys(draft).length;
  const restartHits = items
    .filter((i) => i.spec.restart_required && i.spec.name in draft)
    .map((i) => i.spec.name);

  if (items.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{GROUP_TITLE[group]}</CardTitle>
        {GROUP_NOTE[group] && (
          <CardDescription>{GROUP_NOTE[group]}</CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {items.map((item) => (
          <SettingRow
            key={item.spec.name}
            item={item}
            draftValue={draft[item.spec.name]}
            onChange={(v) =>
              setDraft((prev) => {
                const next = { ...prev };
                if (v === SENTINEL_REMOVE) delete next[item.spec.name];
                else next[item.spec.name] = v;
                return next;
              })
            }
            onReset={() => resetMut.mutate(item.spec.name)}
          />
        ))}

        {restartHits.length > 0 && (
          <p className="rounded border border-warning/40 bg-warning/10 p-2 text-xs text-warning">
            Restart required after save for: {restartHits.join(", ")}. Run{" "}
            <code>make api-restart</code>.
          </p>
        )}

        {error && (
          <div className="rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2">
          {savedAt && Date.now() - savedAt < 3000 && (
            <span className="text-xs text-success">Saved.</span>
          )}
          <Button
            disabled={dirtyCount === 0 || mutation.isPending}
            onClick={() => mutation.mutate(draft)}
          >
            {mutation.isPending
              ? "Saving…"
              : dirtyCount === 0
                ? "No changes"
                : `Save ${dirtyCount} change${dirtyCount === 1 ? "" : "s"}`}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

const SENTINEL_REMOVE = Symbol("remove from draft");

function SettingRow({
  item,
  draftValue,
  onChange,
  onReset,
}: {
  item: SettingItem;
  draftValue: unknown;
  onChange: (v: unknown) => void;
  onReset: () => void;
}) {
  const live = draftValue !== undefined ? draftValue : item.value;
  const kind = item.spec.kind;

  let control: React.ReactNode;
  if (kind === "bool") {
    control = (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(live)}
          onChange={(e) => onChange(e.currentTarget.checked)}
          className="h-4 w-4 accent-accent"
        />
        {live ? "Enabled" : "Disabled"}
      </label>
    );
  } else if (kind === "secret") {
    control = (
      <Input
        type="password"
        value={(draftValue as string) ?? ""}
        placeholder={`current: ${String(item.value || "(unset)")}`}
        onChange={(e) => onChange(e.currentTarget.value)}
        className="font-mono"
      />
    );
  } else if (item.spec.enum_values && item.spec.enum_values.length > 0) {
    control = (
      <select
        value={String(live ?? "")}
        onChange={(e) => onChange(e.currentTarget.value)}
        className="rounded-md border border-border bg-surface px-3 py-2 text-sm"
      >
        {item.spec.enum_values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    );
  } else if (kind === "int" || kind === "float") {
    control = (
      <Input
        type="number"
        step={kind === "float" ? "0.01" : "1"}
        min={item.spec.min_value ?? undefined}
        max={item.spec.max_value ?? undefined}
        value={live as number}
        onChange={(e) => {
          const n = Number(e.currentTarget.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
        className="font-mono"
      />
    );
  } else if (kind === "list_str") {
    // One item per line — much friendlier than a single comma-separated
    // text input when the list has 100+ entries (e.g. the multilingual
    // AI keyword filter).
    const asArray = Array.isArray(live) ? (live as string[]) : [];
    control = (
      <textarea
        value={asArray.join("\n")}
        onChange={(e) =>
          onChange(
            e.currentTarget.value
              .split(/\n+/)
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
        rows={Math.min(16, Math.max(4, asArray.length))}
        className="min-h-[6rem] resize-y rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs"
        placeholder="One item per line"
      />
    );
  } else {
    control = (
      <Input
        type="text"
        value={(live as string) ?? ""}
        onChange={(e) => onChange(e.currentTarget.value)}
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-2 border-b border-border-subtle pb-3 last:border-b-0 md:grid-cols-[1fr_minmax(260px,auto)]">
      <div>
        <Label className="text-sm font-medium">
          {item.spec.label}
          {item.spec.restart_required && (
            <span className="ml-2 inline-block rounded bg-warning/20 px-1.5 py-0.5 text-xs font-semibold text-warning">
              restart
            </span>
          )}
          {item.is_overridden && (
            <span className="ml-2 inline-block rounded bg-info/20 px-1.5 py-0.5 text-xs font-semibold text-info">
              overridden
            </span>
          )}
        </Label>
        <p className="mt-0.5 text-xs text-fg-muted">{item.spec.description}</p>
        <p className="mt-1 font-mono text-xs text-fg-subtle">
          {item.spec.name}
          {(item.spec.min_value !== null || item.spec.max_value !== null) && (
            <>
              {" · "}
              range {item.spec.min_value ?? "−∞"} … {item.spec.max_value ?? "∞"}
            </>
          )}
        </p>
      </div>
      <div className="flex flex-col items-stretch gap-1">
        {control}
        <div className="flex items-center justify-end gap-2">
          {item.is_overridden && (
            <button
              type="button"
              className="text-xs text-fg-muted underline hover:text-fg"
              onClick={onReset}
              title="Drop the override; revert to the env-defined default."
            >
              Reset to default
            </button>
          )}
          {draftValue !== undefined && (
            <button
              type="button"
              className="text-xs text-fg-muted underline hover:text-fg"
              onClick={() => onChange(SENTINEL_REMOVE)}
            >
              Discard edit
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
