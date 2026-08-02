/**
 * Shared client flow for job-backed document uploads (talks, messaging).
 *
 * The server does the heavy lifting (Docling + LLM) as a tracked job and
 * exposes stage + result via a poll endpoint; this hook owns starting the
 * job, polling, elapsed time, and localStorage persistence so a page
 * refresh rejoins the same job instead of orphaning it. Components render
 * from the returned state — no timing or fetch logic in views.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";

type JobStatus<T> = {
  status: string;
  stage: string;
  error?: string | null;
  extracted?: T | null;
};

export function useDocUploadJob<T>(opts: {
  storageKey: string;
  start: (file: File) => Promise<{ job_id: string }>;
  poll: (jobId: string) => Promise<JobStatus<T>>;
  onDone: (extracted: T) => void;
}) {
  const { storageKey, start, poll, onDone } = opts;

  const [jobId, setJobId] = useState<string | null>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? (JSON.parse(raw).job_id as string) : null;
    } catch {
      return null;
    }
  });
  const [startedAt, setStartedAt] = useState<number>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? (JSON.parse(raw).started_at as number) : 0;
    } catch {
      return 0;
    }
  });
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const jobQ = useQuery({
    queryKey: ["doc-upload", storageKey, jobId],
    queryFn: () => poll(jobId!),
    enabled: jobId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "complete" || s === "failed" ? false : 1500;
    },
  });

  useEffect(() => {
    if (!jobId) return;
    const t = setInterval(
      () => setElapsed(Math.max(0, Math.round((Date.now() - startedAt) / 1000))),
      1000,
    );
    return () => clearInterval(t);
  }, [jobId, startedAt]);

  // A dead poll must not brick the UI forever: a 404 means the job row is
  // gone (stale localStorage id, pruned row) — clear immediately; other
  // persistent errors clear after several consecutive failures.
  useEffect(() => {
    if (!jobId || !jobQ.error) return;
    const notFound = jobQ.error instanceof ApiError && jobQ.error.status === 404;
    if (notFound || jobQ.failureCount >= 4) {
      setError(
        notFound
          ? null // stale job id — silent cleanup, nothing user-actionable
          : "Lost contact with the upload job — check the diagnostics page.",
      );
      setJobId(null);
      localStorage.removeItem(storageKey);
    }
  }, [jobQ.error, jobQ.failureCount, jobId, storageKey]);

  useEffect(() => {
    const d = jobQ.data;
    if (!d || !jobId) return;
    if (d.status === "failed") {
      setError(d.error ?? "Extraction failed.");
      setJobId(null);
      localStorage.removeItem(storageKey);
      return;
    }
    if (d.status === "complete" && d.extracted) {
      onDone(d.extracted);
      setJobId(null);
      localStorage.removeItem(storageKey);
    }
    // onDone deliberately omitted from deps: parent callbacks are often
    // re-created per render and the effect must fire on DATA changes only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobQ.data, jobId, storageKey]);

  const begin = useMutation({
    mutationFn: start,
    onSuccess: (r) => {
      setError(null);
      const now = Date.now();
      setStartedAt(now);
      setElapsed(0);
      setJobId(r.job_id);
      localStorage.setItem(
        storageKey,
        JSON.stringify({ job_id: r.job_id, started_at: now }),
      );
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : String(err));
    },
  });

  return {
    busy: begin.isPending || jobId !== null,
    active: jobId !== null,
    stage: jobQ.data?.stage ?? "queued",
    elapsed,
    error,
    upload: (file: File) => begin.mutate(file),
    clearError: () => setError(null),
  };
}

export const UPLOAD_STAGE_LABEL: Record<string, string> = {
  queued: "Queued…",
  parsing: "Reading the document (Docling)…",
  extracting: "Extracting fields (LLM)…",
  done: "Done",
};

export const UPLOAD_STAGE_PCT: Record<string, number> = {
  queued: 10,
  parsing: 45,
  extracting: 85,
  done: 100,
};
