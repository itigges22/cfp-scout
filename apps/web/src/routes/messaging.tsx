import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { Trash2, Upload, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";

import { Pagination } from "@/components/Pagination";
import { Badge } from "@/components/ui/badge";
import { useUnsavedWorkWarning } from "@/hooks/useUnsavedWorkWarning";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { ApiError, messagingApi } from "@/lib/api";
import type {
  DocKind,
  MessagingDocUploadPreview,
  MessagingDocumentCreate,
  MessagingDocumentRead,
} from "@/lib/api-types";
import { ErrorBox } from "@/components/form";
import { TeamGuidance } from "@/components/team/TeamGuidance";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/messaging")({
  component: MessagingPage,
});

const PER_PAGE = 20;

const DOC_KIND_LABELS: Record<DocKind, string> = {
  gtm_strategy: "GTM Strategy",
  content_roadmap: "Content Roadmap",
  other: "Other",
};

function MessagingPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [uploadOpen, setUploadOpen] = useState(false);

  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["messaging", { page, q: debouncedSearch }],
    queryFn: () =>
      messagingApi.list({ page, per_page: PER_PAGE, q: debouncedSearch || undefined }),
  });
  // Deactivate is reversible; a doc used to go inactive and then have no
  // action left on the row at all.
  const restoreDoc = useMutation({
    mutationFn: (d: MessagingDocumentRead) => messagingApi.restore(d),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messaging"] }),
  });
  const deactivate = useMutation({
    mutationFn: (id: string) => messagingApi.deactivate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messaging"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Messaging & positioning"
        description="Active product messaging documents. The matcher's Stage A scores every conference against these."
      />
      <TeamGuidance
        storedHere="Structured messaging documents per product / positioning (elevator pitch, key themes, talking points, differentiators, competitive position). Each one is embedded and used as the comparison corpus for conference matching."
        addInline="+ New messaging document"
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <CardTitle>Messaging documents</CardTitle>
            {query.data ? <Badge variant="muted">{query.data.total} total</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            <Input
              type="search"
              placeholder="Search by title"
              value={search}
              onChange={(e) => {
                setSearch(e.currentTarget.value);
                setPage(1);
              }}
              className="w-64"
            />
            <Button variant="outline" onClick={() => setUploadOpen(true)}>
              <Upload className="mr-1.5 size-4" />
              Upload PDF
            </Button>
            <Link to="/messaging/new">
              <Button>New</Button>
            </Link>
          </div>
        </CardHeader>
        <CardContent>
          {query.isLoading ? (
            <div className="flex flex-col gap-2 py-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : query.isError ? (
            <ErrorBox error={query.error} />
          ) : query.data === undefined || query.data.items.length === 0 ? (
            <div className="rounded-md border border-dashed border-border-strong bg-surface-2 py-10 text-center text-sm text-fg-muted">
              No messaging documents yet.{" "}
              <button
                type="button"
                className="underline hover:text-fg"
                onClick={() => setUploadOpen(true)}
              >
                Upload a GTM Strategy or Content Roadmap PDF
              </button>{" "}
              or <strong>Enter manually</strong> to type the fields in.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Themes</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((m) => (
                  <TableRow
                    key={m.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => navigate({ to: "/messaging/$id", params: { id: m.id } })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate({ to: "/messaging/$id", params: { id: m.id } });
                      }
                    }}
                    className="cursor-pointer hover:bg-surface-2"
                  >
                    <TableCell className="font-medium">{m.title}</TableCell>
                    <TableCell className="text-xs text-fg-muted">
                      {DOC_KIND_LABELS[m.doc_kind as DocKind] ?? m.doc_kind}
                    </TableCell>
                    <TableCell>
                      <Badge variant={m.source_type === "pdf" ? "accent" : "muted"}>
                        {m.source_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {m.key_themes.slice(0, 3).join(" · ")}
                      {m.key_themes.length > 3 ? "…" : null}
                    </TableCell>
                    <TableCell className="text-fg-muted text-xs tabular-nums">
                      {formatDate(m.updated_at)}
                    </TableCell>
                    <TableCell>
                      {m.is_active ? (
                        <Badge variant="success">active</Badge>
                      ) : (
                        <Badge variant="muted">inactive</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {m.is_active ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            deactivate.mutate(m.id);
                          }}
                          disabled={deactivate.isPending}
                          aria-label={`deactivate ${m.title}`}
                          title="Deactivate"
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            restoreDoc.mutate(m);
                          }}
                          disabled={restoreDoc.isPending}
                          aria-label={`restore ${m.title}`}
                          title="Restore"
                        >
                          <RotateCcw className="mr-1 size-4" />
                          Restore
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {query.data ? (
            <Pagination
              page={page}
              perPage={PER_PAGE}
              total={query.data.total}
              onPageChange={setPage}
            />
          ) : null}
        </CardContent>
      </Card>

      {uploadOpen && (
        <UploadReviewDialog
          onClose={() => setUploadOpen(false)}
          onSaved={() => {
            setUploadOpen(false);
            queryClient.invalidateQueries({ queryKey: ["messaging"] });
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload → extract → review → save dialog
// ---------------------------------------------------------------------------

type UploadPhase = "pick" | "extracting" | "review" | "saving";


/** Human names for the save-schema fields, for readable validation errors. */
const FIELD_LABELS: Record<string, string> = {
  title: "Title",
  elevator_pitch: "Elevator pitch",
  target_personas: "Target personas",
  key_themes: "Key themes",
  talking_points: "Talking points",
  differentiators: "Differentiators",
  competitive_position: "Competitive position",
};

/** "One or more fields failed validation" is useless — say which and why. */
function describeSaveError(err: unknown): string {
  if (err instanceof ApiError) {
    const fields = Object.entries(err.fieldErrors());
    if (fields.length) {
      return fields
        .map(([k, msg]) => `${FIELD_LABELS[k.split(".")[0] ?? k] ?? k}: ${msg}`)
        .join(" · ");
    }
    return err.message;
  }
  return String((err as Error).message);
}

function UploadReviewDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [phase, setPhase] = useState<UploadPhase>("pick");
  const [docKind, setDocKind] = useState<DocKind>("other");
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<MessagingDocUploadPreview | null>(null);
  // Nothing persists until the review is confirmed — a refresh mid-extract
  // or mid-review silently discards the work, so intercept the unload.
  useUnsavedWorkWarning(phase !== "pick");

  const extractMut = useMutation({
    mutationFn: ({ file, kind }: { file: File; kind: DocKind }) =>
      messagingApi.uploadPreview(file, kind),
    onSuccess: (data) => {
      setDraft(data);
      setPhase("review");
      setError(null);
    },
    onError: (err) => {
      setError(String((err as Error).message));
      setPhase("pick");
    },
  });

  const saveMut = useMutation({
    mutationFn: (body: MessagingDocumentCreate) =>
      messagingApi.create(body, "ui_admin"),
    onSuccess: () => onSaved(),
    onError: (err) => setError(describeSaveError(err)),
  });

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setPhase("extracting");
    extractMut.mutate({ file, kind: docKind });
  }

  function handleSave() {
    if (!draft) return;
    const body: MessagingDocumentCreate = {
      title: draft.title || "Untitled",
      source_type: "pdf",
      doc_kind: draft.doc_kind as DocKind,
      elevator_pitch: draft.elevator_pitch || "No elevator pitch extracted.",
      target_personas: draft.target_personas.length ? draft.target_personas : ["General audience"],
      key_themes: draft.key_themes.length >= 3
        ? draft.key_themes
        : [...draft.key_themes, ...Array(3 - draft.key_themes.length).fill("To be defined")],
      talking_points: draft.talking_points.length >= 3
        ? draft.talking_points
        : [...draft.talking_points, ...Array(3 - draft.talking_points.length).fill("To be defined")],
      differentiators: draft.differentiators,
      competitive_position: draft.competitive_position,
      pillar_id: null,
      is_active: true,
    };
    setPhase("saving");
    saveMut.mutate(body);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-base font-semibold">
            {phase === "pick" || phase === "extracting"
              ? "Upload positioning document"
              : "Review extracted fields"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-fg-muted hover:text-fg"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {(phase === "pick" || phase === "extracting") && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-fg-muted">
                Upload a GTM Strategy, Content Roadmap, or other positioning PDF. The LLM will
                extract fields — you'll review and edit before saving.
              </p>

              <div className="flex flex-col gap-1">
                <Label>Document type</Label>
                <select
                  value={docKind}
                  onChange={(e) => setDocKind(e.currentTarget.value as DocKind)}
                  className="rounded-md border border-border bg-surface px-3 py-2 text-sm"
                >
                  <option value="gtm_strategy">GTM Strategy</option>
                  <option value="content_roadmap">Content Roadmap</option>
                  <option value="other">Other positioning doc</option>
                </select>
                <p className="text-xs text-fg-muted">
                  Telling the LLM the document type improves extraction quality.
                </p>
              </div>

              <div>
                <Button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={phase === "extracting"}
                >
                  {phase === "extracting" ? "Extracting fields…" : "Choose PDF…"}
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  className="hidden"
                  onChange={handleFile}
                />
              </div>

              {phase === "extracting" && (
                <p className="text-sm text-fg-muted">
                  Parsing the document and extracting fields with the LLM — typically
                  15–60 seconds. Stay on this page: nothing is saved until you review
                  and confirm.
                </p>
              )}

              {error && (
                <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
                  {error}
                </div>
              )}
            </div>
          )}

          {(phase === "review" || phase === "saving") && draft && (
            <ReviewForm
              draft={draft}
              onChange={setDraft}
              error={error}
            />
          )}
        </div>

        {(phase === "review" || phase === "saving") && (
          <div className="flex items-center justify-between border-t border-border px-6 py-3">
            <button
              type="button"
              className="text-sm text-fg-muted underline hover:text-fg"
              onClick={() => { setPhase("pick"); setDraft(null); setError(null); }}
            >
              ← Re-upload
            </button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={handleSave} disabled={phase === "saving"}>
                {phase === "saving" ? "Saving…" : "Save document"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Editable review form for LLM-extracted preview
// ---------------------------------------------------------------------------

function ReviewForm({
  draft,
  onChange,
  error,
}: {
  draft: MessagingDocUploadPreview;
  onChange: (d: MessagingDocUploadPreview) => void;
  error: string | null;
}) {
  function set<K extends keyof MessagingDocUploadPreview>(key: K, value: MessagingDocUploadPreview[K]) {
    onChange({ ...draft, [key]: value });
  }

  function listField(
    key: keyof Pick<MessagingDocUploadPreview, "target_personas" | "key_themes" | "talking_points" | "differentiators">,
    label: string,
    description: string,
    minRows = 3,
  ) {
    const arr = draft[key] as string[];
    return (
      <div className="flex flex-col gap-1">
        <Label className="font-medium">{label}</Label>
        <p className="text-xs text-fg-muted">{description}</p>
        <textarea
          value={arr.join("\n")}
          onChange={(e) =>
            set(key, e.currentTarget.value.split(/\n+/).map((s) => s.trim()).filter(Boolean) as string[] & MessagingDocUploadPreview[typeof key])
          }
          rows={Math.max(minRows, arr.length + 1)}
          className="resize-y rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs"
          placeholder="One item per line"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-fg-muted">
        Review what the LLM extracted. Edit any field before saving — all fields will be
        validated when you click <strong>Save document</strong>.
      </p>

      <div className="flex flex-col gap-1">
        <Label className="font-medium">Document type</Label>
        <select
          value={draft.doc_kind}
          onChange={(e) => set("doc_kind", e.currentTarget.value as DocKind)}
          className="rounded-md border border-border bg-surface px-3 py-2 text-sm"
        >
          <option value="gtm_strategy">GTM Strategy</option>
          <option value="content_roadmap">Content Roadmap</option>
          <option value="other">Other</option>
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <Label className="font-medium">Title</Label>
        <Input
          value={draft.title}
          onChange={(e) => set("title", e.currentTarget.value)}
          placeholder="Document title"
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label className="font-medium">Elevator pitch</Label>
        <p className="text-xs text-fg-muted">
          2-4 sentences capturing the product's value proposition. Min 50 characters.
        </p>
        <textarea
          value={draft.elevator_pitch}
          onChange={(e) => set("elevator_pitch", e.currentTarget.value)}
          rows={4}
          className="resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Describe the product's core value proposition…"
        />
      </div>

      {listField(
        "target_personas",
        "Target personas",
        "Job titles or roles this product targets. One per line. (min 1)",
        3,
      )}

      {listField(
        "key_themes",
        "Key themes",
        "Topic areas and technology themes. One per line. (min 3 — matched against conference topic vocabulary)",
        4,
      )}

      {listField(
        "talking_points",
        "Talking points",
        "Specific claims, proof points, or messages. One per line. (min 3)",
        4,
      )}

      {listField(
        "differentiators",
        "Differentiators",
        "What makes this distinct from alternatives. One per line.",
        2,
      )}

      <div className="flex flex-col gap-1">
        <Label className="font-medium">Competitive position</Label>
        <p className="text-xs text-fg-muted">
          Brief description of the competitive landscape and where this product fits.
        </p>
        <textarea
          value={draft.competitive_position}
          onChange={(e) => set("competitive_position", e.currentTarget.value)}
          rows={2}
          className="resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Optional — leave blank if not applicable"
        />
      </div>

      {error && (
        <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </div>
      )}
    </div>
  );
}
