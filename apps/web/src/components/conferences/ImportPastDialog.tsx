/**
 * ImportPastDialog — upload a spreadsheet of already-attended conferences.
 *
 * The format table is FETCHED from /conferences/import/format, which is
 * served from the same constant the backend parser and the downloadable
 * template are built from — so what this popup shows is, by construction,
 * what the importer accepts. No format knowledge lives in the frontend.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, conferencesApi } from "@/lib/api";

export function ImportPastDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const formatQ = useQuery({
    queryKey: ["conferences", "import-format"],
    queryFn: () => conferencesApi.importFormat(),
    staleTime: 5 * 60_000,
  });

  const upload = useMutation({
    mutationFn: (file: File) => conferencesApi.importPast(file),
    onSuccess: () => {
      setError(null);
      void qc.invalidateQueries({ queryKey: ["conferences"] });
      void qc.invalidateQueries({ queryKey: ["analytics"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? (err.problem.detail ?? err.message) : String(err));
    },
  });

  const result = upload.data;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import past conferences</DialogTitle>
          <DialogDescription>
            One row per conference you already attended. Attendee names are
            matched to your SME roster, so imported history feeds the
            matcher and the analytics.
          </DialogDescription>
        </DialogHeader>

        {/* The format contract, straight from the server */}
        <div className="max-h-64 overflow-y-auto rounded-md border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Column</TableHead>
                <TableHead>What goes in it</TableHead>
                <TableHead>Example</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(formatQ.data ?? []).map((c) => (
                <TableRow key={c.key}>
                  <TableCell className="font-mono text-xs">
                    {c.key}
                    {c.required ? <span className="ml-1 text-danger">*</span> : null}
                  </TableCell>
                  <TableCell className="text-sm text-fg-muted">{c.label}</TableCell>
                  <TableCell className="text-xs text-fg-subtle">{c.example}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" asChild>
            <a href="/api/v1/conferences/import/template">
              <Download className="mr-1.5 h-4 w-4" />
              Download template (.xlsx)
            </a>
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.csv"
            className="hidden"
            onChange={(e) => {
              const f = e.currentTarget.files?.[0];
              if (f) upload.mutate(f);
              e.currentTarget.value = "";
            }}
          />
          <Button
            size="sm"
            disabled={upload.isPending}
            onClick={() => fileRef.current?.click()}
          >
            <Upload className="mr-1.5 h-4 w-4" />
            {upload.isPending ? "Importing…" : "Upload filled sheet"}
          </Button>
          <span className="text-xs text-fg-muted">
            .xlsx or .csv · re-uploading a corrected sheet is safe
          </span>
        </div>

        {error ? (
          <p className="rounded border border-danger/40 bg-danger/10 p-2.5 text-sm text-danger">
            {error}
          </p>
        ) : null}

        {result ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm">
              <span className="font-medium text-success">{result.created} created</span>
              {" · "}
              {result.updated_existing} updated existing
              {result.errors > 0 ? (
                <span className="text-danger"> · {result.errors} errors</span>
              ) : null}
            </p>
            <ul className="max-h-40 space-y-1 overflow-y-auto text-xs text-fg-muted">
              {result.results.map((r) => (
                <li key={r.row}>
                  Row {r.row}: <span className="text-fg">{r.name || "—"}</span> —{" "}
                  {r.outcome}
                  {r.detail ? ` (${r.detail})` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
