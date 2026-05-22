/**
 * /messaging/new — minimal single-page form to create a messaging document.
 *
 * This is the "I have a structured set of fields to type/paste in" path.
 * For unstructured PDFs use the upload endpoint (POST /api/v1/uploads/pdf)
 * which the SettingsLink to "Workbook" docs cover. Either path lands a row
 * in `app.messaging_documents` + auto-enqueues an embedding.
 */

import { useMutation } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/routes/dashboard";
import { messagingApi } from "@/lib/api";

export const Route = createFileRoute("/messaging/new")({
  component: NewMessagingDocPage,
});

function NewMessagingDocPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [elevatorPitch, setElevatorPitch] = useState("");
  const [personas, setPersonas] = useState("");
  const [keyThemes, setKeyThemes] = useState("");
  const [talkingPoints, setTalkingPoints] = useState("");
  const [differentiators, setDifferentiators] = useState("");
  const [competitive, setCompetitive] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      messagingApi.create({
        title: title.trim(),
        source_type: "structured",
        elevator_pitch: elevatorPitch.trim(),
        target_personas: splitLines(personas),
        key_themes: splitLines(keyThemes),
        talking_points: splitLines(talkingPoints),
        differentiators: splitLines(differentiators),
        competitive_position: competitive.trim(),
        is_active: true,
      }),
    onSuccess: () => {
      navigate({ to: "/messaging" });
    },
    onError: (err) => setError(String((err as Error).message)),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    if (elevatorPitch.trim().length < 30) {
      setError("Elevator pitch must be at least 30 characters.");
      return;
    }
    mutation.mutate();
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="New messaging document"
        description="Structured product messaging fields. One per active positioning artifact."
      />
      <Card className="max-w-3xl">
        <CardHeader>
          <CardTitle>Fields</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <FieldRow label="Title" required hint="Short label, ≤120 chars.">
              <Input
                value={title}
                maxLength={120}
                onChange={(e) => setTitle(e.currentTarget.value)}
                placeholder="OpenShift AI 2026 positioning"
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
                placeholder="OpenShift AI is the platform that…"
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

            {error && (
              <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
                {error}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Link to="/messaging">
                <Button variant="outline" type="button">
                  Cancel
                </Button>
              </Link>
              <Button disabled={mutation.isPending}>
                {mutation.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
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
  children: React.ReactNode;
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
