/**
 * Calendar-sync import dialog.
 *
 * Uploads to /api/v1/past-conferences/import-calendar-sync in
 * preview-then-apply mode. Mirrors the shape of the upstream
 * google-calendar-events-sync repo's CSV (Event Name / Complete /
 * Start Date / End Date / City / Country / AI BU On-Site Staff /
 * Description / Activities / Type). Falls back to Docling + LLM
 * extraction if the strict linter rejects the file.
 *
 * UX: drop a file → see the decisions (per-row breakdown grouped by
 * target: past_conference vs conference vs skipped) → Apply or Cancel.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  FileSearch,
  Loader2,
  X,
} from "lucide-react";
import { useState } from "react";

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
import { ApiError } from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Decision {
  source_row: number;
  target: "past_conference" | "conference" | "skipped";
  action: "insert" | "update" | "skip";
  name: string;
  summary: string;
  warnings: string[];
}

interface ImportResult {
  source: "linter" | "docling_fallback";
  skipped_rows: number;
  file_warnings: string[];
  fallback_error: string | null;
  inserted_past: number;
  inserted_conferences: number;
  updated_past: number;
  updated_conferences: number;
  skipped: number;
  unknown_attendees: string[];
  decisions: Decision[];
}

async function postCalendarSync(
  file: File,
  apply: boolean,
): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `/api/v1/past-conferences/import-calendar-sync?apply=${apply}`,
    { method: "POST", body: form },
  );
  const body = await res.json();
  if (!res.ok) {
    throw new ApiError(body);
  }
  return body as ImportResult;
}

export function CalendarSyncImportDialog({ open, onOpenChange }: Props) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [applyResult, setApplyResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const previewMut = useMutation({
    mutationFn: (f: File) => postCalendarSync(f, false),
    onSuccess: (data) => {
      setPreview(data);
      setApplyResult(null);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Preview failed"),
  });

  const applyMut = useMutation({
    mutationFn: (f: File) => postCalendarSync(f, true),
    onSuccess: (data) => {
      setApplyResult(data);
      void qc.invalidateQueries({ queryKey: ["past-conferences"] });
      void qc.invalidateQueries({ queryKey: ["conferences"] });
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Apply failed"),
  });

  const reset = () => {
    setFile(null);
    setPreview(null);
    setApplyResult(null);
    setError(null);
    previewMut.reset();
    applyMut.reset();
  };

  const close = () => {
    reset();
    onOpenChange(false);
  };

  const handleFile = (f: File | null) => {
    setFile(f);
    setPreview(null);
    setApplyResult(null);
    setError(null);
    if (f) previewMut.mutate(f);
  };

  const inFlight = previewMut.isPending || applyMut.isPending;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent widthClass="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Import calendar-sync events</DialogTitle>
          <DialogDescription>
            Upload the CSV exported from the AI BU Developer Marketing 2026
            Events spreadsheet (Events tab). Uses the same column shape as{" "}
            <a
              href="https://github.com/a teammate's calendar-sync utility"
              target="_blank"
              rel="noreferrer noopener"
              className="text-accent underline"
            >
              google-calendar-events-sync
            </a>
            . Falls back to Docling + LLM extraction if the strict linter rejects
            the file. <strong>Complete=TRUE</strong> rows land in past
            conferences; <strong>Complete=FALSE</strong> become approved upcoming
            conferences.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 p-6">
          {/* File picker */}
          {!applyResult && (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">File</span>
              <input
                type="file"
                accept=".csv,.xlsx,.xls,.md,.txt,.pdf"
                onChange={(e) => handleFile(e.currentTarget.files?.[0] ?? null)}
                disabled={inFlight}
                className="rounded border border-border bg-surface px-3 py-2 file:mr-3 file:rounded file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-fg"
              />
              <span className="text-xs text-fg-subtle">
                CSV recommended. Other formats (PDF, XLSX, MD) route through the
                Docling + LLM fallback.
              </span>
            </label>
          )}

          {/* Error */}
          {error && (
            <div className="rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
              {error}
            </div>
          )}

          {/* Preview pane */}
          {preview && !applyResult && (
            <PreviewPane result={preview} />
          )}

          {/* Apply result */}
          {applyResult && (
            <ApplyResultPane result={applyResult} />
          )}
        </div>

        <DialogFooter className="gap-2">
          {!applyResult ? (
            <>
              <Button variant="ghost" onClick={close} disabled={inFlight}>
                Cancel
              </Button>
              <Button
                onClick={() => file && applyMut.mutate(file)}
                disabled={
                  !file ||
                  !preview ||
                  preview.fallback_error != null ||
                  preview.decisions.length === 0 ||
                  inFlight
                }
              >
                {applyMut.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : null}
                Apply ({preview?.decisions.length ?? 0} rows)
              </Button>
            </>
          ) : (
            <Button onClick={close}>Done</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PreviewPane({ result }: { result: ImportResult }) {
  const past = result.decisions.filter((d) => d.target === "past_conference");
  const upcoming = result.decisions.filter((d) => d.target === "conference");
  const hasWarnings =
    result.file_warnings.length > 0 || result.unknown_attendees.length > 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={result.source === "linter" ? "muted" : "accent"}>
          parsed via {result.source}
        </Badge>
        <span className="text-fg-muted">
          {result.decisions.length} row{result.decisions.length === 1 ? "" : "s"}
        </span>
        {result.skipped_rows > 0 && (
          <span className="text-fg-subtle">· {result.skipped_rows} skipped</span>
        )}
      </div>

      {hasWarnings && (
        <div className="flex flex-col gap-1 rounded border border-warning/40 bg-warning/10 p-2 text-xs">
          {result.file_warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-1.5 text-warning">
              <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
              <span>{w}</span>
            </div>
          ))}
          {result.unknown_attendees.length > 0 && (
            <div className="flex items-start gap-1.5 text-warning">
              <AlertTriangle className="mt-0.5 h-3 w-3 flex-shrink-0" />
              <span>
                Unmatched attendee names:{" "}
                <strong>{result.unknown_attendees.join(", ")}</strong>. Add them
                as SMEs first if they should be linked.
              </span>
            </div>
          )}
        </div>
      )}

      {past.length > 0 && (
        <DecisionGroup
          title="Past conferences"
          icon={<FileSearch className="h-3.5 w-3.5" />}
          decisions={past}
        />
      )}
      {upcoming.length > 0 && (
        <DecisionGroup
          title="Upcoming (approved) conferences"
          icon={<CalendarClock className="h-3.5 w-3.5" />}
          decisions={upcoming}
        />
      )}
    </div>
  );
}

function DecisionGroup({
  title,
  icon,
  decisions,
}: {
  title: string;
  icon: React.ReactNode;
  decisions: Decision[];
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-xs uppercase tracking-wider text-fg-subtle">
        {icon}
        <span>
          {title} ({decisions.length})
        </span>
      </div>
      <div className="max-h-64 overflow-y-auto rounded border border-border-subtle">
        <ul className="divide-y divide-border-subtle">
          {decisions.map((d) => (
            <li key={`${d.target}-${d.source_row}`} className="px-2.5 py-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-sm font-medium">{d.name}</span>
                <Badge
                  variant={d.action === "insert" ? "success" : d.action === "update" ? "accent" : "muted"}
                  className="text-[10px]"
                >
                  {d.action}
                </Badge>
              </div>
              <p className="truncate text-xs text-fg-muted">{d.summary}</p>
              {d.warnings.length > 0 && (
                <p className="text-[10px] text-warning">⚠ {d.warnings.join("; ")}</p>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ApplyResultPane({ result }: { result: ImportResult }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 rounded border border-success/40 bg-success/10 p-3 text-sm text-success">
        <CheckCircle2 className="h-4 w-4" />
        <span>
          Import committed. Inserted{" "}
          <strong>
            {result.inserted_past + result.inserted_conferences}
          </strong>
          , updated <strong>{result.updated_past + result.updated_conferences}</strong>
          .
        </span>
      </div>
      <ul className="text-xs text-fg-muted">
        <li>
          Past conferences: +{result.inserted_past} inserted, ~
          {result.updated_past} updated
        </li>
        <li>
          Upcoming conferences: +{result.inserted_conferences} inserted, ~
          {result.updated_conferences} updated
        </li>
        {result.unknown_attendees.length > 0 && (
          <li className="text-warning">
            <X className="inline h-3 w-3" /> Unmatched attendees were skipped:{" "}
            {result.unknown_attendees.join(", ")}
          </li>
        )}
      </ul>
    </div>
  );
}
