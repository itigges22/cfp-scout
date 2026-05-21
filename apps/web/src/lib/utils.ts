import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// `cn` — the standard shadcn-style class-merger. Combines clsx for
// conditional class composition with tailwind-merge for resolving
// conflicts (e.g. p-2 + p-4 → p-4).
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
