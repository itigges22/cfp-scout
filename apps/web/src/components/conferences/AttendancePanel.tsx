/**
 * Who is going, when, and what they will do there — plus how it went.
 *
 * WHY THIS EXISTS
 *   The app displayed "Previously attended" in three places (the map
 *   legend, the conference list badge, a diagnostics counter) and had no
 *   way to set it. Actual cost, leads generated and the worth-it verdict
 *   had columns and endpoints that nothing in the UI ever called.
 *
 *   So the product rendered the answer to "who went and was it worth it"
 *   without ever being able to ask. For a tool whose stated purpose is
 *   "full tracking of all of it", that was the gap.
 *
 * THE SHAPE FOLLOWS THE DATA MODEL
 *   A row with travel dates and no confirmation is a PLAN — the state
 *   between saying yes to a conference and having gone, which is where
 *   most conferences sit most of the time. It becomes attended when the
 *   dates pass, or when somebody says so.
 *
 *   The outcome fields are all optional and stay editable afterwards.
 *   Cost and leads usually arrive weeks late; a form that refused to
 *   save without them would mean nothing got recorded at all.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorBox } from "@/components/form";
import {
  participationApi,
  smesApi,
  type AttendanceSummary,
  type Participation,
  type ParticipationInput,
} from "@/lib/api";

const ACTIVITIES: Participation["activity"][] = [
  "talk",
  "booth",
  "attend",
  "sponsor",
];

const VERDICTS: { value: NonNullable<AttendanceSummary["attendance_verdict"]>; label: string }[] =
  [
    { value: "would_attend", label: "Would attend again" },
    { value: "unsure", label: "Unsure" },
    { value: "would_not_attend", label: "Would not attend again" },
  ];

export function AttendancePanel({ conferenceId }: { conferenceId: string }) {
  const qc = useQueryClient();
  const key = ["conferences", conferenceId, "participation"];

  const people = useQuery({
    queryKey: key,
    queryFn: () => participationApi.list(conferenceId),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["conferences", conferenceId] });
  };

  const remove = useMutation({
    mutationFn: (id: string) => participationApi.remove(id),
    onSuccess: invalidate,
  });
  const mark = useMutation({
    mutationFn: ({ id, attended }: { id: string; attended: boolean }) =>
      participationApi.markAttended(id, attended),
    onSuccess: invalidate,
  });

  const [draft, setDraft] = useState<ParticipationInput>({
    person_label: "",
    activity: "attend",
    arrives_on: "",
    departs_on: "",
  });
  // Multiple SMEs going is the usual case, so team members are toggle
  // chips and one Add creates one participation row per selection —
  // rows linked by sme_id, which is what the per-SME analytics read.
  // The free-text name stays for guests and externals (sme_id null).
  const [selectedSmeIds, setSelectedSmeIds] = useState<string[]>([]);
  const roster = useQuery({
    queryKey: ["smes", "roster"],
    queryFn: () => smesApi.list({ per_page: 100, is_active: true }),
    staleTime: 60_000,
  });
  const smeById = new Map((roster.data?.items ?? []).map((s) => [s.id, s]));

  const canAdd =
    selectedSmeIds.length > 0 || (draft.person_label ?? "").trim().length > 0;

  const submitAll = async () => {
    const base = {
      activity: draft.activity,
      arrives_on: draft.arrives_on || null,
      departs_on: draft.departs_on || null,
    };
    for (const smeId of selectedSmeIds) {
      const s = smeById.get(smeId);
      await participationApi.add(conferenceId, {
        ...base,
        sme_id: smeId,
        person_label: s?.full_name ?? "",
      });
    }
    if ((draft.person_label ?? "").trim()) {
      await participationApi.add(conferenceId, {
        ...base,
        person_label: draft.person_label!.trim(),
      });
    }
  };
  const addAll = useMutation({
    mutationFn: submitAll,
    onSuccess: () => {
      invalidate();
      setSelectedSmeIds([]);
      setDraft({ person_label: "", activity: "attend", arrives_on: "", departs_on: "" });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Who is going</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {people.isError ? <ErrorBox error={people.error} /> : null}
        {addAll.isError ? <ErrorBox error={addAll.error} /> : null}

        {people.isLoading ? (
          <Loader2 className="size-4 animate-spin text-fg-muted" />
        ) : (people.data ?? []).length === 0 ? (
          <p className="text-sm text-fg-muted">
            Nobody recorded yet. Add the first person below — this is what makes
            the conference count as planned, and later as attended.
          </p>
        ) : (
          <ul className="space-y-2">
            {(people.data ?? []).map((p) => (
              <li
                key={p.id}
                className="flex items-start justify-between gap-3 rounded border p-3"
              >
                <div className="min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="text-sm font-medium">{p.person_label}</span>
                    <span className="text-xs text-fg-muted">{p.activity}</span>
                  </div>
                  {p.arrives_on || p.departs_on ? (
                    <p className="mt-0.5 text-xs text-fg-muted">
                      {p.arrives_on ?? "?"} to {p.departs_on ?? "?"}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <label className="flex items-center gap-1 text-xs text-fg-muted">
                    <input
                      type="checkbox"
                      checked={p.has_attended}
                      onChange={(e) =>
                        mark.mutate({ id: p.id, attended: e.target.checked })
                      }
                    />
                    attended
                  </label>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`remove ${p.person_label}`}
                    onClick={() => {
                      if (window.confirm(`Remove ${p.person_label}?`)) {
                        remove.mutate(p.id);
                      }
                    }}
                  >
                    <Trash2 className="size-4 text-fg-subtle" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="grid gap-2 rounded-md border border-border-subtle bg-surface-2 p-4 sm:grid-cols-4">
          <div className="col-span-full">
            <Label>Team members going</Label>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {(roster.data?.items ?? []).map((s) => {
                const on = selectedSmeIds.includes(s.id);
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() =>
                      setSelectedSmeIds((prev) =>
                        on ? prev.filter((x) => x !== s.id) : [...prev, s.id],
                      )
                    }
                    className={
                      on
                        ? "rounded-full border border-accent bg-accent/20 px-3 py-1 text-xs text-fg"
                        : "rounded-full border border-border bg-surface px-3 py-1 text-xs text-fg-muted hover:border-accent/50"
                    }
                  >
                    {on ? "✓ " : ""}
                    {s.full_name}
                  </button>
                );
              })}
              {roster.isLoading ? (
                <span className="text-xs text-fg-muted">Loading team…</span>
              ) : null}
            </div>
          </div>
          <div className="sm:col-span-2">
            <Label htmlFor="ap-name">Guest / other name (optional)</Label>
            <Input
              id="ap-name"
              value={draft.person_label ?? ""}
              placeholder="Someone not on the team roster"
              onChange={(e) => setDraft({ ...draft, person_label: e.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="ap-activity">Doing what</Label>
            <select
              id="ap-activity"
              className="h-9 w-full rounded border bg-surface px-2 text-sm"
              value={draft.activity}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  activity: e.target.value as Participation["activity"],
                })
              }
            >
              {ACTIVITIES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <Button
              className="w-full"
              disabled={!canAdd || addAll.isPending}
              onClick={() => addAll.mutate()}
            >
              <Plus className="size-4" />
              {selectedSmeIds.length > 1
                ? ` Add ${selectedSmeIds.length} people`
                : " Add"}
            </Button>
          </div>
          <div>
            <Label htmlFor="ap-from">Arrives</Label>
            <Input
              id="ap-from"
              type="date"
              value={draft.arrives_on ?? ""}
              onChange={(e) => setDraft({ ...draft, arrives_on: e.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="ap-to">Departs</Label>
            <Input
              id="ap-to"
              type="date"
              value={draft.departs_on ?? ""}
              onChange={(e) => setDraft({ ...draft, departs_on: e.target.value })}
            />
          </div>
        </div>

        <OutcomeForm conferenceId={conferenceId} />
      </CardContent>
    </Card>
  );
}

/**
 * What the event cost and whether it was worth it.
 *
 * Every field optional and editable later — the operator asked for these
 * to be addable "later on if they don't have already", and cost and lead
 * counts genuinely arrive weeks after an event.
 */
function OutcomeForm({ conferenceId }: { conferenceId: string }) {
  const qc = useQueryClient();
  const key = ["conferences", conferenceId, "attendance"];

  const current = useQuery({
    queryKey: key,
    queryFn: () => participationApi.getAttendance(conferenceId),
  });

  const [form, setForm] = useState<AttendanceSummary | null>(null);
  useEffect(() => {
    if (current.data && form === null) setForm(current.data);
  }, [current.data, form]);

  const save = useMutation({
    mutationFn: (body: AttendanceSummary) =>
      participationApi.setAttendance(conferenceId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  if (!form) return null;

  const num = (v: string) => (v === "" ? null : Number(v));

  return (
    <div className="space-y-3 rounded-md border border-border-subtle bg-surface-2 p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-fg-muted">
        How it went
      </p>
      {save.isError ? <ErrorBox error={save.error} /> : null}
      <div className="grid gap-2 sm:grid-cols-3">
        <div>
          <Label htmlFor="of-spend">Actual cost (USD)</Label>
          <Input
            id="of-spend"
            type="number"
            min={0}
            value={form.spend_usd ?? ""}
            onChange={(e) => setForm({ ...form, spend_usd: num(e.target.value) })}
          />
        </div>
        <div>
          <Label htmlFor="of-leads">Leads generated</Label>
          <Input
            id="of-leads"
            type="number"
            min={0}
            value={form.leads_generated ?? ""}
            onChange={(e) =>
              setForm({ ...form, leads_generated: num(e.target.value) })
            }
          />
        </div>
        <div>
          <Label htmlFor="of-verdict">Worth it?</Label>
          <select
            id="of-verdict"
            className="h-9 w-full rounded border bg-surface px-2 text-sm"
            value={form.attendance_verdict ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                attendance_verdict:
                  (e.target.value as AttendanceSummary["attendance_verdict"]) || null,
              })
            }
          >
            <option value="">Not recorded</option>
            {VERDICTS.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <Label htmlFor="of-notes">Notes</Label>
        <Input
          id="of-notes"
          value={form.attendance_notes}
          placeholder="Anything worth remembering next year"
          onChange={(e) => setForm({ ...form, attendance_notes: e.target.value })}
        />
      </div>
      <Button size="sm" onClick={() => save.mutate(form)} disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
