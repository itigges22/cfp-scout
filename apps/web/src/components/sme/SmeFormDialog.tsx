import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useMe } from "@/hooks/useMe";
import { ApiError, audiencesApi, pillarsApi, smesApi, topicsApi } from "@/lib/api";
import type { AudienceProfileRead, PillarRead, SmeCreate, SmeRead } from "@/lib/api-types";
import { ErrorBox, Field } from "@/routes/audiences";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Existing SME → renders as "edit" form. Omitted → create form. */
  initial?: SmeRead | null;
}

const SME_MAX_TOPICS = 5;

const EMPTY_FORM: SmeCreate = {
  full_name: "",
  email: null,
  team: "Engineering",
  primary_topics: [],
  audience_focus: [],
  location_country: "US",
  location_city: null,
  bio: "",
  languages: ["en"],
  external_links: {},
  is_active: true,
};

export function SmeFormDialog({ open, onOpenChange, initial = null }: Props) {
  const queryClient = useQueryClient();
  const { label: meLabel } = useMe();
  const isEdit = initial !== null;
  const [form, setForm] = useState<SmeCreate>(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Reseed when the dialog opens with a different SME (or toggles create↔edit).
  useEffect(() => {
    if (!open) return;
    if (initial) {
      setForm({
        full_name: initial.full_name,
        email: initial.email,
        team: initial.team,
        primary_topics: initial.primary_topics,
        audience_focus: initial.audience_focus,
        location_country: initial.location_country,
        location_city: initial.location_city,
        bio: initial.bio,
        languages: initial.languages,
        external_links: initial.external_links ?? {},
        is_active: initial.is_active,
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setFieldErrors({});
  }, [open, initial]);

  // Fetch the lookups needed for the multi-selects. Both stay open while
  // the dialog is up; cached by React Query.
  const topicsQuery = useQuery({
    queryKey: ["topics", "active-for-sme-picker"],
    queryFn: () => topicsApi.list({ per_page: 200, pending_only: false }),
    enabled: open,
  });
  const audiencesQuery = useQuery({
    queryKey: ["audiences", "active-for-sme-picker"],
    queryFn: () => audiencesApi.list({ per_page: 200, is_active: true }),
    enabled: open,
  });

  const pillarsQuery = useQuery({
    queryKey: ["pillars"],
    queryFn: () => pillarsApi.list(),
    staleTime: 5 * 60 * 1000,
  });

  const mutate = useMutation({
    mutationFn: (body: SmeCreate) => {
      const cleaned = {
        ...body,
        email: body.email?.trim() ? body.email : null,
        location_city: body.location_city?.trim() ? body.location_city : null,
      };
      const actor = meLabel || "user";
      return isEdit && initial
        ? smesApi.update(initial.id, cleaned, actor)
        : smesApi.create(cleaned, actor);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["smes"] });
      setForm(EMPTY_FORM);
      setFieldErrors({});
      onOpenChange(false);
    },
    onError: (err) => {
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors());
    },
  });

  const bioLength = form.bio.length;
  const bioOk = bioLength >= 200 && bioLength <= 2000;
  const audienceOk = form.audience_focus.length >= 1;
  const canSubmit = bioOk && audienceOk;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${initial?.full_name}` : "New SME"}</DialogTitle>
          <DialogDescription>
            Profile quality drives matcher quality. The 200-character bio minimum is intentional —
            empty or terse bios produce poor embeddings and bad recommendations.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-5 p-6">
          {/* ----- Identity ----- */}
          <Section title="Identity">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Full name" error={fieldErrors.full_name}>
                <Input
                  value={form.full_name}
                  onChange={(e) => setForm({ ...form, full_name: e.currentTarget.value })}
                  placeholder="Sarah Chen"
                />
              </Field>
              <Field label="Email (optional)" error={fieldErrors.email}>
                <Input
                  type="email"
                  value={form.email ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, email: e.currentTarget.value || null })
                  }
                  placeholder="sarah@example.com"
                />
              </Field>
            </div>
            <Field label="Team" error={fieldErrors.team}>
              <Input
                value={form.team}
                onChange={(e) => setForm({ ...form, team: e.currentTarget.value })}
                placeholder="Engineering"
              />
            </Field>
          </Section>

          {/* ----- Expertise ----- */}
          <Section title="Expertise & focus">
            <Field label="Primary topics" error={fieldErrors.primary_topics}>
              <PickerHint
                hint={`Select up to ${SME_MAX_TOPICS} topics (${form.primary_topics.length}/${SME_MAX_TOPICS} selected). Approve pending topics in /topics first.`}
              />
              <Picker
                query={topicsQuery}
                renderLabel={(t) => t.name}
                selected={form.primary_topics}
                maxSelect={SME_MAX_TOPICS}
                onChange={(ids) => setForm({ ...form, primary_topics: ids })}
                emptyMessage="No active topics yet. Approve them in /topics or seed via the workbook."
              />
            </Field>

            <Field label="Audiences they speak to well" error={fieldErrors.audience_focus}>
              <PickerHint hint="Pick 1–8 active audiences. Audiences are created under each pillar's Audiences tab." />
              <GroupedAudiencePicker
                audiences={audiencesQuery.data?.items ?? []}
                pillars={pillarsQuery.data ?? []}
                loading={audiencesQuery.isLoading}
                selected={form.audience_focus}
                onChange={(ids) => setForm({ ...form, audience_focus: ids })}
              />
            </Field>
          </Section>

          {/* ----- Location ----- */}
          <Section title="Location">
            <div className="grid grid-cols-3 gap-4">
              <Field
                label="Country code (ISO-3166-1)"
                error={fieldErrors.location_country}
              >
                <Input
                  value={form.location_country}
                  onChange={(e) =>
                    setForm({ ...form, location_country: e.currentTarget.value.toUpperCase() })
                  }
                  placeholder="US"
                  maxLength={2}
                />
              </Field>
              <Field label="City (optional)" error={fieldErrors.location_city}>
                <Input
                  value={form.location_city ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, location_city: e.currentTarget.value || null })
                  }
                  placeholder="Boston"
                />
              </Field>
              <Field label="Languages (ISO-639-1)" error={fieldErrors.languages}>
                <Input
                  value={form.languages.join(", ")}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      languages: e.currentTarget.value
                        .split(/[,\s]+/)
                        .map((s) => s.trim().toLowerCase())
                        .filter(Boolean),
                    })
                  }
                  placeholder="en, ja"
                />
              </Field>
            </div>
          </Section>

          {/* ----- Bio ----- */}
          <Section title="Bio">
            <Field
              label={`Bio — ${bioLength}/2000`}
              error={fieldErrors.bio}
            >
              <Textarea
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.currentTarget.value })}
                placeholder="200–2000 chars. What does this SME work on? What are they known for? What recent talks or papers? The matcher embeds this text and uses it for retrieval — invest the time."
                rows={6}
              />
              <BioGauge length={bioLength} ok={bioOk} />
            </Field>
          </Section>

          {mutate.isError && Object.keys(fieldErrors).length === 0 ? (
            <ErrorBox error={mutate.error} />
          ) : null}

          {/* Inline pre-submit hints so the user knows exactly what's blocking */}
          {!canSubmit && (
            <div className="rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning">
              {!bioOk && bioLength < 200
                ? `Bio needs ${200 - bioLength} more character${200 - bioLength === 1 ? "" : "s"} (minimum 200).`
                : !bioOk
                  ? "Bio is too long — trim to 2000 characters."
                  : null}
              {!audienceOk
                ? " Select at least one audience the SME speaks to."
                : null}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={mutate.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={() => mutate.mutate(form)}
            disabled={mutate.isPending || !canSubmit}
          >
            {mutate.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            {isEdit ? "Save changes" : "Create SME"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-xs font-medium uppercase tracking-wider text-fg-subtle">
        {title}
      </h3>
      {children}
    </div>
  );
}

function GroupedAudiencePicker({
  audiences,
  pillars,
  loading,
  selected,
  onChange,
}: {
  audiences: AudienceProfileRead[];
  pillars: PillarRead[];
  loading: boolean;
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  if (loading) return <Skeleton className="h-20 w-full" />;

  if (audiences.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border-strong bg-surface-2 p-3 text-xs text-fg-muted">
        No audiences yet. Create them under a pillar's <strong>Audiences</strong> tab.
      </div>
    );
  }

  // Build pillar lookup for labels
  const pillarById = new Map(pillars.map((p) => [p.id, p.name]));

  // Group audiences by pillar_id; null → "Unassigned"
  const groups = new Map<string | null, AudienceProfileRead[]>();
  for (const a of audiences) {
    const key = a.pillar_id ?? null;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(a);
  }

  // Order: pillar groups (by display order from pillars list), then unassigned last
  const orderedKeys: (string | null)[] = [
    ...pillars.map((p) => p.id).filter((id) => groups.has(id)),
    ...(groups.has(null) ? [null] : []),
  ];

  const toggle = (id: string) => {
    if (selected.includes(id)) onChange(selected.filter((x) => x !== id));
    else if (selected.length < 8) onChange([...selected, id]);
  };

  return (
    <div className="flex max-h-52 flex-col gap-3 overflow-y-auto rounded-md border border-border bg-surface p-3">
      {orderedKeys.map((key) => {
        const items = groups.get(key) ?? [];
        const groupLabel = key ? (pillarById.get(key) ?? "Unknown pillar") : "Unassigned";
        return (
          <div key={key ?? "unassigned"}>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-fg-subtle">
              {groupLabel}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {items.map((a) => {
                const on = selected.includes(a.id);
                const atCap = !on && selected.length >= 8;
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => toggle(a.id)}
                    disabled={atCap}
                    className="focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Badge variant={on ? "accent" : "muted"} className="cursor-pointer">
                      {a.name}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PickerHint({ hint }: { hint: string }) {
  return <p className="text-xs text-fg-subtle">{hint}</p>;
}

function BioGauge({ length, ok }: { length: number; ok: boolean }) {
  // Visual cue: too short / OK / too long.
  const percent = Math.min(100, (length / 2000) * 100);
  const color = !ok && length < 200 ? "bg-warning" : ok ? "bg-success" : "bg-danger";
  return (
    <div className="mt-1 flex h-1 w-full overflow-hidden rounded-full bg-surface-2">
      <div className={`${color} transition-all`} style={{ width: `${percent}%` }} />
    </div>
  );
}

interface PickerItem {
  id: string;
}

interface PickerProps<T extends PickerItem> {
  query: {
    isLoading: boolean;
    isError: boolean;
    data: { items: T[] } | undefined;
  };
  renderLabel: (item: T) => string;
  selected: string[];
  maxSelect?: number;
  onChange: (ids: string[]) => void;
  emptyMessage: string;
}

function Picker<T extends PickerItem>({
  query,
  renderLabel,
  selected,
  maxSelect,
  onChange,
  emptyMessage,
}: PickerProps<T>) {
  if (query.isLoading) {
    return <Skeleton className="h-20 w-full" />;
  }
  if (query.isError || !query.data) {
    return (
      <div className="rounded-md border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
        Failed to load options.
      </div>
    );
  }
  if (query.data.items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border-strong bg-surface-2 p-3 text-xs text-fg-muted">
        {emptyMessage}
      </div>
    );
  }

  const isSelected = (id: string) => selected.includes(id);
  const atCap = maxSelect !== undefined && selected.length >= maxSelect;
  const toggle = (id: string) => {
    if (isSelected(id)) onChange(selected.filter((x) => x !== id));
    else if (!atCap) onChange([...selected, id]);
  };

  return (
    <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto rounded-md border border-border bg-surface p-2">
      {query.data.items.map((item) => {
        const on = isSelected(item.id);
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => toggle(item.id)}
            disabled={!on && atCap}
            className="focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Badge variant={on ? "accent" : "muted"} className="cursor-pointer">
              {renderLabel(item)}
            </Badge>
          </button>
        );
      })}
    </div>
  );
}
