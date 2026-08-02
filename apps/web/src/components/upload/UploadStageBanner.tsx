/**
 * The staged progress banner every job-backed document upload renders —
 * one look, one set of copy, whether it's a talk, a GTM strategy, or a
 * content roadmap. Stage + elapsed come from useDocUploadJob.
 */
import { UPLOAD_STAGE_LABEL, UPLOAD_STAGE_PCT } from "@/hooks/useDocUploadJob";

export function UploadStageBanner({
  stage,
  elapsed,
}: {
  stage: string;
  elapsed: number;
}) {
  return (
    <div className="mx-1 my-3 flex flex-col gap-2 rounded-lg border border-accent/40 bg-accent/5 px-4 py-3.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-fg">{UPLOAD_STAGE_LABEL[stage] ?? stage}</span>
        <span className="tabular-nums text-fg-muted">{elapsed}s</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full bg-accent transition-all duration-700"
          style={{ width: `${UPLOAD_STAGE_PCT[stage] ?? 10}%` }}
        />
      </div>
      <p className="text-xs text-fg-muted">
        Large documents can take a few minutes — the first one on a fresh pod
        is the slowest. Safe to refresh; this picks back up.
      </p>
    </div>
  );
}
