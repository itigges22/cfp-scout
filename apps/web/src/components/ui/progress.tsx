/**
 * Score / progress bar — a small, dependency-free CSS bar that takes a
 * value in [0, 1] and renders a filled track. Used by the matcher panels
 * (plan 20) to show messaging / pillar / SME score breakdowns.
 *
 * Three visual buckets keyed off the value:
 *   value >= 0.70 — strong (green / success)
 *   value >= 0.45 — okay   (amber / warning)
 *   else          — weak   (red / danger)
 *
 * Previously referenced bg-accent-strong / bg-danger-muted, which
 * aren't defined in our theme — Tailwind silently dropped them so the
 * bars rendered as bare gray tracks. Now uses the standard success /
 * warning / danger tokens that actually exist in styles/index.css.
 *
 * Accessible via aria-valuenow / aria-valuemin / aria-valuemax.
 */

import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export interface ProgressProps extends Omit<HTMLAttributes<HTMLDivElement>, "value"> {
  /** Score in [0, 1]. Values outside the range are clamped. */
  value: number;
  /** Compact height for inline use. */
  size?: "sm" | "md";
}

function bucketClass(value: number): string {
  if (value >= 0.7) return "bg-success";
  if (value >= 0.45) return "bg-warning";
  return "bg-danger";
}

export function Progress({ value, size = "md", className, ...rest }: ProgressProps) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const heightClass = size === "sm" ? "h-1.5" : "h-2";
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("w-full overflow-hidden rounded-full bg-surface-3", heightClass, className)}
      {...rest}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-300", bucketClass(clamped))}
        style={{ width: `${clamped * 100}%` }}
      />
    </div>
  );
}
