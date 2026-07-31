import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { AlertTriangle, Loader2, Plus, Trash2, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, conferencesApi, pillarsApi, talksApi } from "@/lib/api";
import type {
  PillarRead,
  TalkCreate,
  TalkFormat,
  TalkRead,
  TalkReviewStatus,
  TalkSubmissionCreate,
  TalkUpdate,
} from "@/lib/api-types";
import { PageHeader } from "@/routes/dashboard";
import { ErrorBox } from "@/components/form";

export const Route = createFileRoute("/talks")({
  component: TalksPage,
});

const REVIEW_FILTERS: { value: TalkReviewStatus | null; label: string }[] = [
  { value: null, label: "All" },
  { value: "draft", label: "Draft" },
  { value: "pending_review", label: "Pending review" },
  { value: "approved", label: "Approved" },
];

const STATUS_VARIANT: Record<TalkReviewStatus, "muted" | "accent" | "warning"> = {
  draft: "muted",
  pending_review: "warning",
  approved: "accent",
};

const FORMATS: TalkFormat[] = ["keynote", "talk", "panel", "workshop", "tutorial", "other"];

function TalksPage() {
  const qc = useQueryClient();
  const [pillarFilter, setPillarFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<TalkReviewStatus | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<TalkRead | null>(null);


  const pillarsQuery = useQuery({
    queryKey: ["pillars"],
    queryFn: () => pillarsApi.list(),
  });

  const talksQuery = useQuery({
    queryKey: ["talks", { pillar_id: pillarFilter, review_status: statusFilter }],
    queryFn: () =>
      talksApi.list({
        per_page: 100,
        pillar_id: pillarFilter ?? undefined,
        review_status: statusFilter ?? undefined,
      }),
  });

  const deleteTalk = useMutation({
    mutationFn: (id: string) => talksApi.delete(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["talks"] }),
  });

  const talks = talksQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Talks Library"
        description="Track and manage talk abstracts. Submit talks to conferences and monitor reuse risk."
      />

      {/* Actions — one button. Uploading a document is a way of STARTING a
          talk, not a separate operation on the library, so it lives inside
          the new-talk pane rather than beside it. */}
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-2 size-4" />
          New talk
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-fg-subtle">Pillar:</span>
          <button
            onClick={() => setPillarFilter(null)}
            className={`rounded px-2 py-0.5 text-xs ${pillarFilter === null ? "bg-accent text-white" : "text-fg-muted hover:text-fg"}`}
          >
            All
          </button>
          {(pillarsQuery.data ?? []).map((p) => (
            <button
              key={p.id}
              onClick={() => setPillarFilter(p.id)}
              className={`rounded px-2 py-0.5 text-xs ${pillarFilter === p.id ? "bg-accent text-white" : "text-fg-muted hover:text-fg"}`}
            >
              {p.name}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-fg-subtle">Status:</span>
          {REVIEW_FILTERS.map((f) => (
            <button
              key={f.value ?? "all"}
              onClick={() => setStatusFilter(f.value)}
              className={`rounded px-2 py-0.5 text-xs ${statusFilter === f.value ? "bg-accent text-white" : "text-fg-muted hover:text-fg"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            {talksQuery.isLoading
              ? "Loading…"
              : `${talks.length} talk${talks.length !== 1 ? "s" : ""}`}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {talksQuery.isLoading ? (
            <div className="flex flex-col gap-2 p-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : talksQuery.isError ? (
            <div className="p-4">
              <ErrorBox error={talksQuery.error} />
            </div>
          ) : talks.length === 0 ? (
            <div className="p-8 text-center text-sm text-fg-muted">
              No talks yet.{" "}
              <button
                onClick={() => setShowCreate(true)}
                className="text-accent underline hover:no-underline"
              >
                Create one
              </button>{" "}
              to get started.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Format</TableHead>
                  <TableHead>Submissions</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {talks.map((talk) => (
                  <TableRow
                    key={talk.id}
                    role="button"
                    tabIndex={0}
                    className="cursor-pointer hover:bg-surface-2"
                    onClick={() => setEditing(talk)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setEditing(talk);
                      }
                    }}
                  >
                    <TableCell className="font-medium">{talk.title}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[talk.review_status as TalkReviewStatus] ?? "muted"}>
                        {talk.review_status.replace("_", " ")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {talk.talk_format ?? "—"}
                    </TableCell>
                    <TableCell>
                      <UsageGauge talk={talk} />
                    </TableCell>
                    <TableCell className="text-xs text-fg-muted">
                      {formatDate(talk.updated_at)}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          // Destructive and previously unconfirmed — one
                          // stray click removed an abstract and its whole
                          // submission history.
                          if (
                            !window.confirm(
                              `Delete "${talk.title}"? Its submission history goes too.`,
                            )
                          ) {
                            return;
                          }
                          deleteTalk.mutate(talk.id);
                        }}
                        disabled={deleteTalk.isPending}
                        aria-label="delete talk"
                      >
                        <Trash2 className="size-4 text-fg-subtle" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <TalkDialog
        open={showCreate}
        initial={null}
        pillars={pillarsQuery.data ?? []}
        onOpenChange={(o) => { if (!o) setShowCreate(false); }}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["talks"] });
          setShowCreate(false);
        }}
      />

      <TalkDialog
        open={editing !== null}
        initial={editing}
        pillars={pillarsQuery.data ?? []}
        onOpenChange={(o) => { if (!o) setEditing(null); }}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["talks"] });
          setEditing(null);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Talk create / edit dialog
// ---------------------------------------------------------------------------

const EMPTY_TALK: TalkCreate = {
  title: "",
  // Both carry server-side defaults ("manual" / true). Stated here because
  // the generated type includes defaulted fields, and because a form that
  // relies on an invisible default is one rename away from being wrong.
  source_type: "manual",
  is_active: true,
  abstract: null,
  pillar_id: null,
  talk_format: null,
  suggested_duration_minutes: null,
  review_status: "draft",
};

function TalkDialog({
  open,
  initial,
  pillars,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  initial: TalkRead | null;
  pillars: PillarRead[];
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const isEdit = initial !== null;
  const [form, setForm] = useState<TalkCreate>(EMPTY_TALK);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Uploading a document PRE-FILLS this form rather than opening a second
  // review dialog. There used to be two: a toolbar "Upload document" button
  // that opened its own near-identical form, which meant two places to keep
  // in step and two answers to "where do I add a talk?".
  // Upload is a tracked backend job: POST returns a job id instantly, and
  // we poll real stages (queued → parsing → extracting) so the operator
  // watches progress instead of a spinner. Elapsed time shown because
  // Docling legitimately takes ~a minute on a cold pod.
  const [uploadJob, setUploadJob] = useState<string | null>(null);
  const [uploadStart, setUploadStart] = useState<number>(0);
  const [elapsed, setElapsed] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const jobQ = useQuery({
    queryKey: ["talk-upload", uploadJob],
    queryFn: () => talksApi.uploadStatus(uploadJob!),
    enabled: uploadJob !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "complete" || s === "failed" ? false : 1500;
    },
  });
  useEffect(() => {
    if (!uploadJob) return;
    const t = setInterval(() => setElapsed(Math.round((Date.now() - uploadStart) / 1000)), 1000);
    return () => clearInterval(t);
  }, [uploadJob, uploadStart]);
  useEffect(() => {
    const d = jobQ.data;
    if (!d || !uploadJob) return;
    if (d.status === "failed") {
      setUploadError(d.error ?? "Extraction failed.");
      setUploadJob(null);
      return;
    }
    if (d.status === "complete" && d.extracted) {
      const ex = d.extracted;
      const suggested = pillars.find(
        (p) => p.name.toLowerCase() === (ex.suggested_pillar_name ?? "").toLowerCase(),
      );
      setForm((prev) => ({
        ...prev,
        title: ex.title || prev.title,
        abstract: ex.abstract ?? prev.abstract,
        pillar_id: suggested?.id ?? prev.pillar_id,
        talk_format: (ex.talk_format as TalkFormat | null) ?? prev.talk_format,
        suggested_duration_minutes:
          ex.suggested_duration_minutes ?? prev.suggested_duration_minutes,
      }));
      setUploadJob(null);
    }
  }, [jobQ.data, uploadJob, pillars]);
  const upload = useMutation({
    mutationFn: (file: File) => talksApi.upload(file),
    onSuccess: (r) => {
      setUploadError(null);
      setUploadStart(Date.now());
      setElapsed(0);
      setUploadJob(r.job_id);
    },
    onError: (err) => {
      setUploadError(err instanceof ApiError ? err.message : String(err));
    },
  });
  const uploadBusy = upload.isPending || uploadJob !== null;
  const stage = jobQ.data?.stage ?? "queued";
  const STAGE_LABEL: Record<string, string> = {
    queued: "Queued…",
    parsing: "Reading the document (Docling)…",
    extracting: "Extracting talk fields (LLM)…",
    done: "Done",
  };
  const STAGE_PCT: Record<string, number> = { queued: 10, parsing: 45, extracting: 85, done: 100 };

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setForm({
        ...EMPTY_TALK,
        title: initial.title,
        abstract: initial.abstract,
        pillar_id: initial.pillar_id,
        talk_format: initial.talk_format,
        suggested_duration_minutes: initial.suggested_duration_minutes,
        review_status: initial.review_status,
      });
    } else {
      setForm(EMPTY_TALK);
    }
    setFieldErrors({});
  }, [open, initial]);

  const mutate = useMutation({
    mutationFn: (body: TalkCreate) => {
      if (isEdit && initial) {
        return talksApi.update(initial.id, body as TalkUpdate);
      }
      return talksApi.create(body);
    },
    onSuccess: onSaved,
    onError: (err) => {
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors());
    },
  });

  const setField = <K extends keyof TalkCreate>(k: K, v: TalkCreate[K]) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit "${initial?.title}"` : "New talk"}</DialogTitle>
        </DialogHeader>

        {/* Start from a document. Creation only — on an existing talk this
            would silently overwrite fields the user already curated. */}
        {!isEdit && (
          <div className="flex items-center gap-3 rounded-lg border border-dashed border-border bg-surface-2/50 px-4 py-3">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadBusy}
            >
              {uploadBusy ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <Upload className="mr-2 size-4" />
              )}
              Fill from a document
            </Button>
            <span className="text-xs text-fg-muted">
              PDF, DOCX or TXT — the fields below are filled in for you to check.
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.docx"
              className="hidden"
              onChange={(e) => {
                const file = e.currentTarget.files?.[0];
                if (file) {
                  upload.mutate(file);
                  e.currentTarget.value = "";
                }
              }}
            />
          </div>
        )}
        {uploadJob !== null ? (
          <div className="flex flex-col gap-1.5 rounded-lg border border-accent/40 bg-accent/5 px-4 py-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-fg">{STAGE_LABEL[stage] ?? stage}</span>
              <span className="tabular-nums text-fg-muted">{elapsed}s</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full bg-accent transition-all duration-700"
                style={{ width: `${STAGE_PCT[stage] ?? 10}%` }}
              />
            </div>
            <p className="text-xs text-fg-muted">
              First document on a fresh pod takes the longest — the parser
              loads its models once, then later uploads are much faster.
            </p>
          </div>
        ) : null}
        {uploadError ? <p className="text-sm text-danger">{uploadError}</p> : null}
        <div className="flex flex-col gap-4 p-6">
          <FieldWrap label="Title *" error={fieldErrors.title}>
            <Input
              value={form.title}
              onChange={(e) => setField("title", e.currentTarget.value)}
              placeholder="e.g. AI at the Edge: Patterns for Hybrid Cloud"
            />
          </FieldWrap>

          <FieldWrap label="Abstract" error={fieldErrors.abstract}>
            <Textarea
              value={form.abstract ?? ""}
              onChange={(e) => setField("abstract", e.currentTarget.value || null)}
              placeholder="One to three paragraph summary of the talk."
              rows={4}
            />
          </FieldWrap>

          <div className="grid grid-cols-2 gap-4">
            <FieldWrap label="Format" error={fieldErrors.talk_format}>
              <select
                className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm"
                value={form.talk_format ?? ""}
                onChange={(e) =>
                  setField("talk_format", (e.currentTarget.value as TalkFormat) || null)
                }
              >
                <option value="">— none —</option>
                {FORMATS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </FieldWrap>

            <FieldWrap label="Duration (min)" error={fieldErrors.suggested_duration_minutes}>
              <Input
                type="number"
                min={1}
                value={form.suggested_duration_minutes ?? ""}
                onChange={(e) =>
                  setField(
                    "suggested_duration_minutes",
                    e.currentTarget.value ? Number(e.currentTarget.value) : null,
                  )
                }
                placeholder="45"
              />
            </FieldWrap>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <FieldWrap label="Pillar" error={fieldErrors.pillar_id}>
              <select
                className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm"
                value={form.pillar_id ?? ""}
                onChange={(e) => setField("pillar_id", e.currentTarget.value || null)}
              >
                <option value="">— none —</option>
                {pillars.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </FieldWrap>

            <FieldWrap label="Review status" error={fieldErrors.review_status}>
              <select
                className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm"
                value={form.review_status ?? "draft"}
                onChange={(e) =>
                  setField("review_status", e.currentTarget.value as TalkReviewStatus)
                }
              >
                <option value="draft">Draft</option>
                <option value="pending_review">Pending review</option>
                <option value="approved">Approved</option>
              </select>
            </FieldWrap>
          </div>

          {isEdit && initial ? (
            <>
              <hr className="border-border-subtle" />
              <SubmissionsPanel talk={initial} />
            </>
          ) : null}

          {mutate.isError &&
            mutate.error instanceof ApiError &&
            Object.keys(fieldErrors).length === 0 ? (
            <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
              {mutate.error.message}
            </div>
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
            disabled={mutate.isPending || !form.title.trim()}
          >
            {mutate.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
            {isEdit ? "Save changes" : "Create talk"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Usage gauge — colored pill in the submissions column
// ---------------------------------------------------------------------------
function UsageGauge({ talk }: { talk: TalkRead }) {
  const n = talk.times_applied ?? talk.submissions.length;
  const flagged = talk.is_flagged;
  if (flagged) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-danger/15 px-2 py-0.5 text-xs font-semibold text-danger">
        <AlertTriangle className="size-3" />
        {n} · flagged
      </span>
    );
  }
  if (n === 0) return <span className="text-xs text-fg-subtle">—</span>;
  const variant = n >= 2 ? "bg-warning/15 text-warning" : "bg-surface-2 text-fg-muted";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${variant}`}>
      {n}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Submit-to-conference inline form (inside TalkDialog edit mode)
// ---------------------------------------------------------------------------
const OUTCOMES = ["submitted", "accepted", "rejected", "withdrawn"] as const;

function SubmissionsPanel({ talk }: { talk: TalkRead }) {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confSearch, setConfSearch] = useState("");
  const [selectedConf, setSelectedConf] = useState<{ id: string; name: string } | null>(null);
  const [outcome, setOutcome] = useState<string>("");
  const [submittedAt, setSubmittedAt] = useState<string>("");
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  const confsQ = useQuery({
    queryKey: ["conferences", "talk-picker"],
    queryFn: () => conferencesApi.list({ per_page: 200 }),
    enabled: showForm,
    staleTime: 60_000,
  });

  const submitMut = useMutation({
    mutationFn: (body: TalkSubmissionCreate) => talksApi.submit(talk.id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["talks"] });
      setShowForm(false);
      setConfirming(false);
      setSelectedConf(null);
      setOutcome("");
      setSubmittedAt("");
      setSubmitErr(null);
    },
    onError: (err) => {
      setSubmitErr(err instanceof ApiError ? err.message : String(err));
    },
  });

  const handleAdd = () => {
    if (!selectedConf) return;
    if (talk.is_flagged && !confirming) {
      setConfirming(true);
      return;
    }
    submitMut.mutate({
      conference_id: selectedConf.id,
      outcome: outcome || null,
      submitted_at: submittedAt || null,
    });
  };

  const alreadyAppliedIds = new Set(talk.submissions.map((s) => s.conference_id));
  const conferences = (confsQ.data?.items ?? []).filter(
    (c) =>
      !alreadyAppliedIds.has(c.id) &&
      (!confSearch || c.name.toLowerCase().includes(confSearch.toLowerCase())),
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-fg-subtle">
          Conference submissions ({talk.times_applied ?? talk.submissions.length})
        </p>
        {!showForm && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="text-xs text-accent hover:underline"
          >
            + Apply to conference
          </button>
        )}
      </div>

      {talk.is_flagged && (
        <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-xs text-warning">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>
            This talk has been applied to {talk.times_applied} conferences — it may feel
            repetitive to audiences. Adding another submission is allowed but note the
            high-reuse risk.
          </span>
        </div>
      )}

      {/* Existing submissions list */}
      {talk.submissions.length > 0 && (
        <ul className="space-y-1">
          {talk.submissions.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 text-xs">
              <Link
                to="/conferences/$id"
                params={{ id: s.conference_id }}
                className="truncate text-fg hover:underline"
              >
                {s.conference_name ?? `${s.conference_id.slice(0, 8)}…`}
              </Link>
              <span className="flex shrink-0 items-center gap-2 text-fg-subtle">
                {s.outcome ? (
                  <span className={outcomeColor(s.outcome)}>{s.outcome}</span>
                ) : (
                  <span className="text-fg-subtle">pending</span>
                )}
                {s.submitted_at ? s.submitted_at : null}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Add-submission form */}
      {showForm && (
        <div className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3">
          {confirming && (
            <div className="rounded border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
              This talk is already flagged for high reuse. Confirm to add another submission.
            </div>
          )}
          <div className="flex flex-col gap-1">
            <Label className="text-xs">Search conference</Label>
            <Input
              value={confSearch}
              onChange={(e) => { setConfSearch(e.currentTarget.value); setSelectedConf(null); }}
              placeholder="Type to search…"
              className="h-8 text-sm"
            />
            {confSearch.length > 0 && !selectedConf && (
              <div className="max-h-40 overflow-y-auto rounded-md border border-border bg-surface shadow-sm">
                {confsQ.isLoading ? (
                  <p className="p-2 text-xs text-fg-muted">Searching…</p>
                ) : conferences.length === 0 ? (
                  <p className="p-2 text-xs text-fg-muted">No matches.</p>
                ) : (
                  conferences.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className="flex w-full items-center px-3 py-1.5 text-left text-xs hover:bg-surface-2"
                      onClick={() => { setSelectedConf({ id: c.id, name: c.name }); setConfSearch(c.name); }}
                    >
                      {c.name}
                    </button>
                  ))
                )}
              </div>
            )}
            {selectedConf && (
              <p className="text-xs text-success">Selected: {selectedConf.name}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <Label className="text-xs">Outcome (optional)</Label>
              <select
                value={outcome}
                onChange={(e) => setOutcome(e.currentTarget.value)}
                className="h-8 rounded-md border border-border bg-surface px-2 text-xs"
              >
                <option value="">— none —</option>
                {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs">Submitted date (optional)</Label>
              <Input
                type="date"
                value={submittedAt}
                onChange={(e) => setSubmittedAt(e.currentTarget.value)}
                className="h-8 text-xs"
              />
            </div>
          </div>

          {submitErr && (
            <p className="text-xs text-danger">{submitErr}</p>
          )}

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              className="text-xs text-fg-muted hover:text-fg"
              onClick={() => { setShowForm(false); setConfirming(false); setSelectedConf(null); setConfSearch(""); setSubmitErr(null); }}
            >
              Cancel
            </button>
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={!selectedConf || submitMut.isPending}
            >
              {submitMut.isPending ? <Loader2 className="size-3 animate-spin" /> : null}
              {confirming ? "Confirm anyway" : "Apply"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function outcomeColor(outcome: string) {
  switch (outcome) {
    case "accepted": return "text-success font-medium";
    case "rejected": return "text-danger";
    case "withdrawn": return "text-fg-muted";
    default: return "text-fg-subtle";
  }
}

function FieldWrap({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
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
