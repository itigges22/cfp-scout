import { useMutation } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Operational tunables, reference data, and workbook import/export."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SettingsLink
          to="/settings/tunables"
          title="Tunables & API keys"
          description="LLM API key + budget, matcher gates and weights, SME and team scoring weights, decay, discovery, scraper politeness, logging."
        />
        <SettingsLink
          to="/topics"
          title="Topic review"
          description="LLM-discovered topics pending admin approval. Approve to add to the active vocabulary; reject to deactivate."
        />
        <SettingsLink
          to="/diagnostics"
          title="Diagnostics"
          description="Operational health: jobs, scraper runs, LLM cost / errors, freshness histogram. The page admins check first when something feels off."
        />
        <SettingsLink
          to="/agent"
          title="Agent chat"
          description="Free-form Q&A over your seeded data. Not the main entry point — most questions are easier to answer by clicking the relevant conference or SME."
        />
      </div>

      <WorkbookCard />
    </div>
  );
}

function SettingsLink({
  to,
  title,
  description,
}: {
  to: string;
  title: string;
  description: string;
}) {
  return (
    <Link to={to} className="block">
      <Card className="transition-colors hover:border-border-strong hover:bg-surface-2">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
      </Card>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Workbook (plan 31) — inline actions: download template, export current,
// preview-import + apply-import. No dedicated subroute; the entire flow fits
// in one card.
// ---------------------------------------------------------------------------

type WorkbookDiff = {
  summary: { inserts: number; updates: number; deletes: number; errors: number };
  by_sheet: Record<
    string,
    { inserts: number; updates: number; deletes: number; errors: number }
  >;
  errors: Array<{ sheet: string; row: number; field: string; message: string }>;
};

function WorkbookCard() {
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<WorkbookDiff | null>(null);
  const [applyResult, setApplyResult] = useState<{
    applied: { audit_writes: number; embeddings_enqueued: number };
    summary: WorkbookDiff["summary"];
  } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const downloadTemplate = () => {
    window.location.href = "/api/v1/config/workbook-template";
  };
  const exportCurrent = () => {
    window.location.href = "/api/v1/config/export-workbook";
  };

  const previewMut = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/v1/config/preview-import", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) throw new Error(`Preview failed: HTTP ${res.status}`);
      return (await res.json()) as WorkbookDiff;
    },
    onSuccess: (data) => {
      setPreview(data);
      setApplyResult(null);
      setErrorMessage(null);
    },
    onError: (err) => setErrorMessage(String((err as Error).message)),
  });

  const applyMut = useMutation({
    mutationFn: async ({ file, deletes }: { file: File; deletes: number }) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("confirm_deletes", String(deletes));
      const res = await fetch("/api/v1/config/import-workbook", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`Apply failed: HTTP ${res.status} ${body}`);
      }
      return (await res.json()) as {
        applied: { audit_writes: number; embeddings_enqueued: number };
        summary: WorkbookDiff["summary"];
      };
    },
    onSuccess: (data) => {
      setApplyResult(data);
      setErrorMessage(null);
    },
    onError: (err) => setErrorMessage(String((err as Error).message)),
  });

  const handleFile = (file: File | null) => {
    setPendingFile(file);
    setPreview(null);
    setApplyResult(null);
    setErrorMessage(null);
    if (file) previewMut.mutate(file);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workbook import / export</CardTitle>
        <CardDescription>
          Round-trip the team's reference data (pillars, audiences, SMEs,
          topics, series) via XLSX. Round-trip identity: export → re-import
          without edits is a no-op.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={downloadTemplate}>
            Download empty template
          </Button>
          <Button variant="outline" onClick={exportCurrent}>
            Export current state
          </Button>
          <Button onClick={() => fileInput.current?.click()}>
            Upload &amp; preview…
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
          />
        </div>

        {previewMut.isPending && (
          <p className="text-sm text-fg-muted">Computing diff…</p>
        )}

        {errorMessage && (
          <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            {errorMessage}
          </div>
        )}

        {preview && pendingFile && (
          <PreviewBlock
            file={pendingFile}
            diff={preview}
            applying={applyMut.isPending}
            onApply={() =>
              applyMut.mutate({
                file: pendingFile,
                deletes: preview.summary.deletes,
              })
            }
            result={applyResult}
          />
        )}
      </CardContent>
    </Card>
  );
}

function PreviewBlock({
  file,
  diff,
  applying,
  onApply,
  result,
}: {
  file: File;
  diff: WorkbookDiff;
  applying: boolean;
  onApply: () => void;
  result:
    | {
        applied: { audit_writes: number; embeddings_enqueued: number };
        summary: WorkbookDiff["summary"];
      }
    | null;
}) {
  const { summary, by_sheet, errors } = diff;
  const blocked = summary.errors > 0;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-3 rounded border border-border-subtle bg-surface-2 p-3">
        <span className="text-sm font-semibold">{file.name}</span>
        <span className="text-sm text-fg-muted">
          {summary.inserts} insert{summary.inserts === 1 ? "" : "s"},{" "}
          {summary.updates} update{summary.updates === 1 ? "" : "s"},{" "}
          {summary.deletes} delete{summary.deletes === 1 ? "" : "s"},{" "}
          <span
            className={
              summary.errors > 0 ? "font-semibold text-danger" : undefined
            }
          >
            {summary.errors} error{summary.errors === 1 ? "" : "s"}
          </span>
        </span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wider text-fg-muted">
          <tr className="border-b border-border-subtle">
            <th className="py-1 text-left">Sheet</th>
            <th className="py-1 text-right">Insert</th>
            <th className="py-1 text-right">Update</th>
            <th className="py-1 text-right">Delete</th>
            <th className="py-1 text-right">Errors</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(by_sheet).map(([sheet, counts]) => (
            <tr key={sheet} className="border-b border-border-subtle/60">
              <td className="py-1 font-medium">{sheet}</td>
              <td className="py-1 text-right tabular-nums">{counts.inserts}</td>
              <td className="py-1 text-right tabular-nums">{counts.updates}</td>
              <td className="py-1 text-right tabular-nums">{counts.deletes}</td>
              <td
                className={`py-1 text-right tabular-nums ${counts.errors > 0 ? "text-danger" : ""}`}
              >
                {counts.errors}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {errors.length > 0 && (
        <details className="rounded border border-danger/40 bg-danger/5 p-3 text-sm">
          <summary className="cursor-pointer font-medium text-danger">
            {errors.length} validation error{errors.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-fg">
            {errors.slice(0, 25).map((e, i) => (
              <li key={i}>
                <span className="font-mono text-fg-muted">
                  {e.sheet} row {e.row} · {e.field}
                </span>{" "}
                — {e.message}
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={blocked || applying} onClick={onApply}>
          {applying
            ? "Applying…"
            : blocked
              ? "Fix errors first"
              : summary.deletes > 0
                ? `Apply (and confirm ${summary.deletes} delete${summary.deletes === 1 ? "" : "s"})`
                : "Apply"}
        </Button>
        {result && (
          <span className="text-sm text-fg-muted">
            Applied: {result.summary.inserts} ins / {result.summary.updates} upd
            / {result.summary.deletes} del · audit rows{" "}
            {result.applied.audit_writes}, embeddings enqueued{" "}
            {result.applied.embeddings_enqueued}
          </span>
        )}
      </div>
    </div>
  );
}
