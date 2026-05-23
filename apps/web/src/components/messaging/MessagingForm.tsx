/**
 * Structured messaging-document form. Shared between:
 *   - /messaging/new   → create
 *   - /messaging/$id   → edit
 *
 * Owns the form state; parent handles routing + side effects via the
 * submit callback. Same component pattern as SmeFormDialog / AudienceDialog
 * — keeps editing semantics consistent across the three reference-data
 * sections.
 */

import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MessagingDocumentCreate, MessagingDocumentRead } from "@/lib/api-types";

interface Props {
  /** Existing doc → "edit"; null → "create". */
  initial: MessagingDocumentRead | null;
  /** Disable submit + tweak labels while a save is in flight. */
  submitting: boolean;
  /** Server-side error (validation / 4xx / 5xx) surfaced under the form. */
  error: string | null;
  /** Called with a fully-built MessagingDocumentCreate payload. */
  onSubmit: (body: MessagingDocumentCreate) => void;
  /** "Cancel" button click — parent decides where to route. */
  onCancel: () => void;
}

export function MessagingForm({
  initial,
  submitting,
  error,
  onSubmit,
  onCancel,
}: Props) {
  const [title, setTitle] = useState("");
  const [elevatorPitch, setElevatorPitch] = useState("");
  const [personas, setPersonas] = useState("");
  const [keyThemes, setKeyThemes] = useState("");
  const [talkingPoints, setTalkingPoints] = useState("");
  const [differentiators, setDifferentiators] = useState("");
  const [competitive, setCompetitive] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (initial) {
      setTitle(initial.title);
      setElevatorPitch(initial.elevator_pitch);
      setPersonas(initial.target_personas.join("\n"));
      setKeyThemes(initial.key_themes.join("\n"));
      setTalkingPoints(initial.talking_points.join("\n"));
      setDifferentiators(initial.differentiators.join("\n"));
      setCompetitive(initial.competitive_position);
    } else {
      setTitle("");
      setElevatorPitch("");
      setPersonas("");
      setKeyThemes("");
      setTalkingPoints("");
      setDifferentiators("");
      setCompetitive("");
    }
    setLocalError(null);
  }, [initial]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (!title.trim()) {
      setLocalError("Title is required.");
      return;
    }
    if (elevatorPitch.trim().length < 30) {
      setLocalError("Elevator pitch must be at least 30 characters.");
      return;
    }
    onSubmit({
      title: title.trim(),
      // Edit keeps the original source_type; new docs are always "structured"
      // because this form is the structured-entry path.
      source_type: initial?.source_type ?? "structured",
      elevator_pitch: elevatorPitch.trim(),
      target_personas: splitLines(personas),
      key_themes: splitLines(keyThemes),
      talking_points: splitLines(talkingPoints),
      differentiators: splitLines(differentiators),
      competitive_position: competitive.trim(),
      is_active: initial?.is_active ?? true,
    });
  };

  const isEdit = initial !== null;
  const visibleError = error ?? localError;

  return (
    <Card className="max-w-3xl">
      <CardHeader>
        <CardTitle>{isEdit ? "Fields" : "Fields"}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FieldRow label="Title" required hint="Short label, ≤120 chars.">
            <Input
              value={title}
              maxLength={120}
              onChange={(e) => setTitle(e.currentTarget.value)}
              placeholder="AI platform 2026 positioning"
            />
          </FieldRow>
          <FieldRow
            label="Elevator pitch"
            required
            hint="30–500 chars. The 1–2 sentence framing you'd give a stranger."
          >
            <textarea
              value={elevatorPitch}
              onChange={(e) => setElevatorPitch(e.currentTarget.value)}
              rows={3}
              className="min-h-[5rem] rounded-md border border-border bg-surface px-3 py-2 text-sm"
              placeholder="AI platform is the platform that…"
            />
          </FieldRow>
          <FieldRow
            label="Target personas"
            hint="One per line. e.g. Platform engineer, ML platform lead."
          >
            <textarea
              value={personas}
              onChange={(e) => setPersonas(e.currentTarget.value)}
              rows={3}
              className="min-h-[5rem] rounded-md border border-border bg-surface px-3 py-2 text-sm"
            />
          </FieldRow>
          <FieldRow
            label="Key themes"
            hint="One per line. The 3–6 narrative beats this document leans on."
          >
            <textarea
              value={keyThemes}
              onChange={(e) => setKeyThemes(e.currentTarget.value)}
              rows={3}
              className="min-h-[5rem] rounded-md border border-border bg-surface px-3 py-2 text-sm"
            />
          </FieldRow>
          <FieldRow
            label="Talking points"
            hint="One per line. Specific sentences the SME can paraphrase on stage."
          >
            <textarea
              value={talkingPoints}
              onChange={(e) => setTalkingPoints(e.currentTarget.value)}
              rows={4}
              className="min-h-[6rem] rounded-md border border-border bg-surface px-3 py-2 text-sm"
            />
          </FieldRow>
          <FieldRow
            label="Differentiators"
            hint="One per line. What's true here that isn't true of competitors."
          >
            <textarea
              value={differentiators}
              onChange={(e) => setDifferentiators(e.currentTarget.value)}
              rows={3}
              className="min-h-[5rem] rounded-md border border-border bg-surface px-3 py-2 text-sm"
            />
          </FieldRow>
          <FieldRow
            label="Competitive position"
            hint="Optional paragraph naming the competitive landscape and our angle."
          >
            <textarea
              value={competitive}
              onChange={(e) => setCompetitive(e.currentTarget.value)}
              rows={3}
              className="min-h-[5rem] rounded-md border border-border bg-surface px-3 py-2 text-sm"
            />
          </FieldRow>

          {visibleError && (
            <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              {visibleError}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
            <Button disabled={submitting}>
              {submitting ? "Saving…" : isEdit ? "Save changes" : "Save"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function FieldRow({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-sm">
        {label} {required ? <span className="text-danger">*</span> : null}
      </Label>
      {children}
      {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
    </div>
  );
}

function splitLines(s: string): string[] {
  return s
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}
