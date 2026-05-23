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
import { ApiError, audiencesApi, smesApi, topicsApi } from "@/lib/api";
import type { SmeCreate, SmeRead } from "@/lib/api-types";
import { ErrorBox, Field, ListField } from "@/routes/audiences";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Existing SME → renders as "edit" form. Omitted → create form. */
  initial?: SmeRead | null;
}

const EMPTY_FORM: SmeCreate = {
  full_name: "",
  email: null,
  team: "team",
  expertise_areas: ["", ""],
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
        expertise_areas:
          initial.expertise_areas.length >= 2
            ? initial.expertise_areas
            : [...initial.expertise_areas, ...Array(2 - initial.expertise_areas.length).fill("")],
        primary_topics: initial.primary_topics,
        audience_focus: initial.audience_focus,
        location_country: initial.location_country,
        location_city: initial.location_city,
        bio: initial.bio,
        languages: initial.languages,
        external_links: initial.external_links,
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

  const mutate = useMutation({
    mutationFn: (body: SmeCreate) => {
      const cleaned = {
        ...body,
        expertise_areas: body.expertise_areas.filter((s) => s.trim().length > 0),
        email: body.email?.trim() ? body.email : null,
        location_city: body.location_city?.trim() ? body.location_city : null,
      };
      return isEdit && initial
        ? smesApi.update(initial.id, cleaned)
        : smesApi.create(cleaned);
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
                  placeholder="sarah@redhat.com"
                />
              </Field>
            </div>
            <Field label="Team" error={fieldErrors.team}>
              <Input
                value={form.team}
                onChange={(e) => setForm({ ...form, team: e.currentTarget.value })}
                placeholder="team"
              />
            </Field>
          </Section>

          {/* ----- Expertise ----- */}
          <Section title="Expertise & focus">
            <ListField
              label="Expertise areas"
              hint="2–10 items"
              values={form.expertise_areas}
              error={fieldErrors.expertise_areas}
              onChange={(i, v) => {
                const next = [...form.expertise_areas];
                next[i] = v;
                setForm({ ...form, expertise_areas: next });
              }}
              onAdd={() =>
                setForm({ ...form, expertise_areas: [...form.expertise_areas, ""] })
              }
            />

            <Field label="Primary topics" error={fieldErrors.primary_topics}>
              <PickerHint hint="Pick 2–15 active topics. Approve pending topics in /topics first if needed." />
              <Picker
                query={topicsQuery}
                renderLabel={(t) => t.name}
                selected={form.primary_topics}
                onChange={(ids) => setForm({ ...form, primary_topics: ids })}
                emptyMessage="No active topics yet. Approve them in /topics or seed via the workbook (plan 31)."
              />
            </Field>

            <Field label="Audiences they speak to well" error={fieldErrors.audience_focus}>
              <PickerHint hint="Pick 1–8 active audiences." />
              <Picker
                query={audiencesQuery}
                renderLabel={(a) => a.name}
                selected={form.audience_focus}
                onChange={(ids) => setForm({ ...form, audience_focus: ids })}
                emptyMessage="No audiences yet. Create one on /audiences first."
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

          {/* ----- Links ----- */}
          <Section title="External links (optional)">
            <div className="grid grid-cols-3 gap-4">
              <Field label="LinkedIn URL">
                <Input
                  value={form.external_links.linkedin ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      external_links: {
                        ...form.external_links,
                        linkedin: e.currentTarget.value || null,
                      },
                    })
                  }
                />
              </Field>
              <Field label="GitHub URL">
                <Input
                  value={form.external_links.github ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      external_links: {
                        ...form.external_links,
                        github: e.currentTarget.value || null,
                      },
                    })
                  }
                />
              </Field>
              <Field label="Website URL">
                <Input
                  value={form.external_links.website ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      external_links: {
                        ...form.external_links,
                        website: e.currentTarget.value || null,
                      },
                    })
                  }
                />
              </Field>
            </div>
          </Section>

          {mutate.isError && Object.keys(fieldErrors).length === 0 ? (
            <ErrorBox error={mutate.error} />
          ) : null}
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
            disabled={mutate.isPending || !bioOk || form.expertise_areas.filter((s) => s.trim()).length < 2}
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
  onChange: (ids: string[]) => void;
  emptyMessage: string;
}

function Picker<T extends PickerItem>({
  query,
  renderLabel,
  selected,
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
  const toggle = (id: string) => {
    if (isSelected(id)) onChange(selected.filter((x) => x !== id));
    else onChange([...selected, id]);
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
            className="focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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
