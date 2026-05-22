import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileUp, Loader2, X } from "lucide-react";
import { useState, type DragEvent } from "react";

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
import { ApiError, pastConferencesApi } from "@/lib/api";
import type { PastConferenceImportResult } from "@/lib/api-types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CsvImportDialog({ open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<PastConferenceImportResult | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const importMutation = useMutation({
    mutationFn: ({ file, ignoreErrors }: { file: File; ignoreErrors: boolean }) =>
      pastConferencesApi.importCsv(file, ignoreErrors),
    onSuccess: (data) => {
      setResult(data);
      setServerError(null);
      if (data.imported > 0) {
        void queryClient.invalidateQueries({ queryKey: ["past-conferences"] });
      }
    },
    onError: (err) => {
      setServerError(err instanceof ApiError ? err.message : "Upload failed.");
    },
  });

  const reset = () => {
    setFile(null);
    setResult(null);
    setServerError(null);
    importMutation.reset();
  };

  const close = () => {
    reset();
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent widthClass="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import past conferences (CSV)</DialogTitle>
          <DialogDescription>
            Columns: <code>name, year, attended_by_names, role, session_type, notes</code>. SMEs
            are matched by case-insensitive <code>full_name</code> against active SMEs;
            <code> attended_by_names</code> is semicolon-separated. The default is an
            all-or-nothing transaction — any error rolls everything back. See{" "}
            <code>docs/ops/data-guardrails.md</code> for the per-field rules.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 p-6">
          {!result ? (
            <FileDropZone
              file={file}
              onChange={setFile}
              disabled={importMutation.isPending}
            />
          ) : (
            <ImportResultView
              result={result}
              onTryAgain={reset}
              onCommitWithIgnore={
                file && result.imported === 0 && result.errors.length > 0
                  ? () =>
                      importMutation.mutate({
                        file,
                        ignoreErrors: true,
                      })
                  : undefined
              }
              committing={importMutation.isPending}
            />
          )}

          {serverError ? (
            <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
              {serverError}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={close} disabled={importMutation.isPending}>
            {result ? "Done" : "Cancel"}
          </Button>
          {!result ? (
            <Button
              disabled={!file || importMutation.isPending}
              onClick={() => file && importMutation.mutate({ file, ignoreErrors: false })}
            >
              {importMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <FileUp className="size-4" />
              )}
              {importMutation.isPending ? "Validating…" : "Preview & validate"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Drop zone
// ---------------------------------------------------------------------------
function FileDropZone({
  file,
  onChange,
  disabled,
}: {
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = useState(false);

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) onChange(dropped);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={[
        "flex flex-col items-center justify-center gap-3 rounded-md border-2 border-dashed p-10 text-center transition-colors",
        dragging
          ? "border-accent bg-accent/10"
          : "border-border-strong bg-surface-2",
        disabled ? "opacity-50 pointer-events-none" : "",
      ].join(" ")}
    >
      {file ? (
        <>
          <FileUp className="size-8 text-accent" />
          <div className="text-sm">
            <span className="font-medium">{file.name}</span>
            <span className="ml-2 text-fg-muted">({Math.round(file.size / 1024)} KB)</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onChange(null)}
            disabled={disabled}
          >
            <X className="size-3" /> Choose a different file
          </Button>
        </>
      ) : (
        <>
          <FileUp className="size-8 text-fg-subtle" />
          <div className="text-sm text-fg-muted">
            Drop a CSV here, or{" "}
            <label className="cursor-pointer font-medium text-accent hover:underline">
              browse
              <input
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                disabled={disabled}
                onChange={(e) => {
                  const picked = e.currentTarget.files?.[0];
                  if (picked) onChange(picked);
                }}
              />
            </label>
          </div>
          <div className="text-xs text-fg-subtle">
            Comma-separated, UTF-8. First row is the header.
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result view
// ---------------------------------------------------------------------------
function ImportResultView({
  result,
  onTryAgain,
  onCommitWithIgnore,
  committing,
}: {
  result: PastConferenceImportResult;
  onTryAgain: () => void;
  onCommitWithIgnore?: () => void;
  committing: boolean;
}) {
  const ok = result.imported > 0;
  const hasErrors = result.errors.length > 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={ok ? "success" : hasErrors ? "danger" : "muted"}>
          {ok ? (
            <CheckCircle2 className="mr-1 size-3" />
          ) : (
            <AlertTriangle className="mr-1 size-3" />
          )}
          {ok ? `${result.imported} rows imported` : "No rows imported"}
        </Badge>
        {hasErrors ? (
          <Badge variant="danger">{result.errors.length} row error(s)</Badge>
        ) : null}
        {result.skipped > 0 && !hasErrors ? (
          <Badge variant="muted">{result.skipped} skipped</Badge>
        ) : null}
      </div>

      {result.note ? (
        <p className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
          {result.note}
        </p>
      ) : null}

      {hasErrors ? (
        <div className="flex flex-col gap-1.5 rounded-md border border-border bg-surface p-3 max-h-64 overflow-y-auto">
          <div className="text-xs font-medium uppercase tracking-wider text-fg-subtle">
            Row errors
          </div>
          {result.errors.slice(0, 50).map((e, i) => (
            <div key={i} className="text-xs">
              <span className="font-mono text-fg-muted">row {e.row}</span>
              <span className="ml-2 font-medium">{e.field}</span>
              <span className="ml-2 text-danger">{e.message}</span>
            </div>
          ))}
          {result.errors.length > 50 ? (
            <div className="text-xs text-fg-subtle">
              … and {result.errors.length - 50} more.
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" onClick={onTryAgain}>
          Choose another file
        </Button>
        {onCommitWithIgnore ? (
          <Button size="sm" onClick={onCommitWithIgnore} disabled={committing}>
            {committing ? <Loader2 className="size-4 animate-spin" /> : null}
            Commit valid rows anyway (skip errors)
          </Button>
        ) : null}
      </div>
    </div>
  );
}
