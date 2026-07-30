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
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useMe } from "@/hooks/useMe";
import { ApiError, audiencesApi, pillarsApi, smesApi } from "@/lib/api";
import type { AudienceProfileRead, PillarRead, SmeCreate, SmeRead } from "@/lib/api-types";
import { ErrorBox, Field } from "@/components/form";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Existing SME → renders as "edit" form. Omitted → create form. */
  initial?: SmeRead | null;
  /**
   * Pillar to pre-select when creating. SMEs belong to a pillar, so the
   * dialog is normally opened FROM one — this seeds it so the person is
   * linked on save rather than created loose and linked afterwards.
   */
  defaultPillarId?: string | null;
}

const EMPTY_FORM: SmeCreate = {
  full_name: "",
  email: null,
  team: "Engineering",
  expertise: "",
  audience_focus: [],
  location_country: "US",
  location_city: null,
  bio: "",
  languages: ["en"],
  external_links: {},
  is_active: true,
  // Strategic pillars. The sme_pillars junction and its link endpoints
  // already existed but only the PILLAR page could reach them, so an SME
  // added here was saved with no pillar and the matcher had less to work
  // with than the data model allowed for.
  pillar_ids: [],
};

export function SmeFormDialog({
  open,
  onOpenChange,
  initial = null,
  defaultPillarId = null,
}: Props) {
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
        expertise: initial.expertise ?? "",
        audience_focus: initial.audience_focus,
        location_country: initial.location_country,
        location_city: initial.location_city,
        bio: initial.bio,
        languages: initial.languages,
        external_links: initial.external_links ?? {},
        is_active: initial.is_active,
        pillar_ids: initial.pillar_ids ?? [],
      });
    } else {
      setForm({
        ...EMPTY_FORM,
        pillar_ids: defaultPillarId ? [defaultPillarId] : [],
      });
    }
    setFieldErrors({});
  }, [open, initial, defaultPillarId]);

  // Fetch the lookups needed for the multi-selects. Both stay open while
  // the dialog is up; cached by React Query.
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
      // Creating/editing may change pillar links, and each pillar page has
      // its own SME list (["pillars", id, "smes"]) — prefix covers them all.
      void queryClient.invalidateQueries({ queryKey: ["pillars"] });
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
  // Audiences are no longer required to save. They sharpen matching, so the
  // form still nudges for one — but a fresh install has no audiences yet and
  // blocking on it made the very first SME impossible to create.
  const audienceOk = form.audience_focus.length >= 1;
  // A pillar is REQUIRED, create and edit alike. An SME is pillar-owned —
  // one with no pillar is invisible to the part of the matcher that asks
  // "who covers this theme", so allowing it just creates broken rows.
  // Enforced here rather than in the API schema: bulk imports and restore
  // replay legacy rows that may predate the rule.
  const pillarOk = (form.pillar_ids ?? []).length >= 1;
  const canSubmit = bioOk && pillarOk;

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
            <Field label="Strategic pillars" error={fieldErrors.pillar_ids}>
              <PickerHint hint="Required — every SME belongs to at least one pillar. Drives which conferences they are matched against." />
              <div className="flex flex-wrap gap-2">
                {(pillarsQuery.data ?? []).map((p: PillarRead) => {
                  const on = (form.pillar_ids ?? []).includes(p.id);
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() =>
                        setForm((prev) => ({
                          ...prev,
                          pillar_ids: on
                            ? (prev.pillar_ids ?? []).filter((x) => x !== p.id)
                            : [...(prev.pillar_ids ?? []), p.id],
                        }))
                      }
                      className={[
                        "rounded-full border px-3 py-1 text-sm transition-colors",
                        on
                          ? "border-accent bg-accent/15 text-accent"
                          : "border-border text-fg-muted hover:bg-surface-2",
                      ].join(" ")}
                    >
                      {p.name}
                    </button>
                  );
                })}
                {(pillarsQuery.data ?? []).length === 0 && (
                  <span className="text-sm text-fg-subtle">
                    No pillars yet — create one under Pillars first.
                  </span>
                )}
              </div>
            </Field>

            {/* Replaced the "Primary topics" vocabulary picker. It asked people
                to self-describe by scanning 130+ machine-extracted entries, so
                they skipped it — and the matcher scored that skip as a hard 0.
                Free text goes into the same embedding as the bio, which is the
                dimension the ranker actually weights. */}
            <Field label="What do they work on?" error={fieldErrors.expertise}>
              <PickerHint hint="Their own words — projects, themes, favourite talking points. This feeds matching directly; more specific is better." />
              <textarea
                className="min-h-28 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg"
                maxLength={6000}
                placeholder={
                  "e.g. ITS Hub (inference-time scaling) — better answers by letting the model think longer at answer time, no retraining. My favourite topic, often misunderstood around tokenomics on-prem…"
                }
                value={form.expertise ?? ""}
                onChange={(e) => setForm({ ...form, expertise: e.currentTarget.value })}
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
          {canSubmit && !audienceOk && (
            <div className="rounded-md border border-border bg-surface-2 px-3 py-2 text-xs text-fg-muted">
              No audience selected. Optional, but it sharpens which conferences
              this person is matched to.
            </div>
          )}
          {!canSubmit && (
            <div className="rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning">
              {!bioOk && bioLength < 200
                ? `Bio needs ${200 - bioLength} more character${200 - bioLength === 1 ? "" : "s"} (minimum 200).`
                : !bioOk
                  ? "Bio is too long — trim to 2000 characters."
                  : null}
              {!pillarOk
                ? " Pick at least one strategic pillar — every SME belongs to one."
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

