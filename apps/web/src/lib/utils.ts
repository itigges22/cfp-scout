import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// `cn` — the standard shadcn-style class-merger. Combines clsx for
// conditional class composition with tailwind-merge for resolving
// conflicts (e.g. p-2 + p-4 → p-4).
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * A timestamp as a short local date, or an em dash when absent.
 *
 * Three routes each wrote `new Date(x).toLocaleDateString()` inline, which
 * meant three different answers for a null value — "Invalid Date", the epoch,
 * or a crash — depending on which page you were on.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}
