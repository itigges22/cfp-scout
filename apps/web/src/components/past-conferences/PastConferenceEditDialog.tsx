/**
 * Past-conference edit dialog.
 *
 * Open with `initial=row` to edit an existing past conference; open with
 * `initial=null` to create a new one (the form starts blank). Mirrors the
 * AudienceDialog / SmeFormDialog pattern: parent owns the open state +
 * which row is being edited; this component owns the form state.
 *
 * Schema validation rejects empty attendee lists (min_length=1), so the
 * SME picker is gated — you can't save until at least one SME is selected.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

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
import { Textarea } from "@/components/ui/textarea";
import { ApiError, pastConferencesApi, smesApi } from "@/lib/api";
import type {
  PastConferenceCreate,
  PastConferenceRead,
  PastConferenceRole,
  PastConferenceSessionType,
} from "@/lib/api-types";

const ROLES: PastConferenceRole[] = ["attendee", "speaker", "sponsor", "organizer"];
const SESSION_TYPES: PastConferenceSessionType[] = [
  "keynote",
  "talk",
  "panel",
  "workshop",
  "poster",
];

const CURRENT_YEAR = new Date().getFullYear();

const EMPTY: PastConferenceCreate = {
  name: "",
  year: CURRENT_YEAR,
  series_id: null,
  attended_sme_ids: [],
  role: "attendee",
  session_type: null,
  notes: "",
  imported_from: null,
};

interface Props {
  open: boolean;
  initial: PastConferenceRead | null;
  onOpenChange: (open: boolean) => void;
}

export function PastConferenceEditDialog({ open, initial, onOpenChange }: Props) {
  const qc = useQueryClient();
  const isEdit = initial !== null;
  const [form, setForm] = useState<PastConferenceCreate>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const smesQ = useQuery({
    queryKey: ["smes", "active-for-past-picker"],
    queryFn: () => smesApi.list({ per_page: 200 }),
    enabled: open,
  });

  // Reseed when the dialog opens with a different row.
  useEffect(() => {
    if (!open) return;
    if (initial) {
      setForm({
        name: initial.name,
        year: initial.year,
        series_id: initial.series_id,
        attended_sme_ids: [...initial.attended_sme_ids],
        role: initial.role,
        session_type: initial.session_type,
        notes: initial.notes ?? "",
        imported_from: initial.imported_from,
      });
    } else {
      setForm(EMPTY);
    }
    setFieldErrors({});
  }, [open, initial]);

  const saveMut = useMutation({
    mutationFn: (body: PastConferenceCreate) =>
      isEdit && initial
        ? pastConferencesApi.update(initial.id, body)
        : pastConferencesApi.create(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["past-conferences"] });
      onOpenChange(false);
    },
    onError: (err) => {
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors());
    },
  });

  const toggleSme = (id: string) => {
    setForm((prev) => ({
      ...prev,
      attended_sme_ids: prev.attended_sme_ids.includes(id)
        ? prev.attended_sme_ids.filter((x) => x !== id)
        : [...prev.attended_sme_ids, id],
    }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent widthClass="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Edit "${initial?.name}"` : "New past conference"}
          </DialogTitle>
          <DialogDescription>
            Past conferences power the matcher's past-attendance bonus — when
            an SME has been to a series before, future editions of that series
            get a small boost in the SME ranker.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 p-6">
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <Field label="Name" error={fieldErrors.name}>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
                placeholder="KubeCon EU 2026"
                maxLength={150}
              />
            </Field>
            <Field label="Year" error={fieldErrors.year}>
              <Input
                type="number"
                value={form.year}
                onChange={(e) =>
                  setForm({
                    ...form,
                    year: Number.parseInt(e.currentTarget.value, 10) || CURRENT_YEAR,
                  })
                }
                min={1990}
                max={CURRENT_YEAR}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Role" error={fieldErrors.role}>
              <select
                value={form.role}
                onChange={(e) =>
                  setForm({ ...form, role: e.currentTarget.value as PastConferenceRole })
                }
                className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Session type (optional)" error={fieldErrors.session_type}>
              <select
                value={form.session_type ?? ""}
                onChange={(e) => {
                  const v = e.currentTarget.value;
                  setForm({
                    ...form,
                    session_type:
                      v === "" ? null : (v as PastConferenceSessionType),
                  });
                }}
                className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm"
              >
                <option value="">— none —</option>
                {SESSION_TYPES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field
            label={`Attendees (${form.attended_sme_ids.length} selected, at least 1 required)`}
            error={fieldErrors.attended_sme_ids}
          >
            <p className="text-xs text-fg-subtle">
              Click to toggle. Only active SMEs are listed.
            </p>
            <div className="mt-1 flex max-h-40 flex-wrap gap-2 overflow-y-auto rounded-md border border-border bg-surface p-2">
              {smesQ.isLoading ? (
                <p className="text-xs text-fg-muted">Loading SMEs…</p>
              ) : smesQ.data?.items.length === 0 ? (
                <p className="text-xs text-fg-muted">
                  No active SMEs yet. Add some on /smes first.
                </p>
              ) : (
                smesQ.data?.items.map((s) => {
                  const on = form.attended_sme_ids.includes(s.id);
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => toggleSme(s.id)}
                      className="focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      <Badge
                        variant={on ? "accent" : "muted"}
                        className="cursor-pointer"
                      >
                        {s.full_name}
                      </Badge>
                    </button>
                  );
                })
              )}
            </div>
          </Field>

          <Field label="Notes (optional)" error={fieldErrors.notes}>
            <Textarea
              value={form.notes ?? ""}
              onChange={(e) =>
                setForm({ ...form, notes: e.currentTarget.value })
              }
              rows={3}
              placeholder="Anything worth remembering about this event — sponsorship value, demo highlights, follow-ups, etc."
            />
          </Field>

          {initial?.imported_from && (
            <p className="text-xs text-fg-subtle">
              Imported from: <code>{initial.imported_from}</code>
            </p>
          )}

          {saveMut.isError && !(saveMut.error instanceof ApiError) ? (
            <div className="rounded border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
              {String((saveMut.error as Error)?.message)}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={saveMut.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={() => saveMut.mutate(form)}
            disabled={
              saveMut.isPending ||
              !form.name.trim() ||
              form.attended_sme_ids.length === 0
            }
          >
            {saveMut.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : null}
            {isEdit ? "Save changes" : "Create past conference"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | undefined;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
      {error ? <span className="text-xs text-danger">{error}</span> : null}
    </div>
  );
}
