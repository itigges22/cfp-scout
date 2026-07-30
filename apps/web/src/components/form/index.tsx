/**
 * Shared form primitives: a labelled field, a repeatable list field, and
 * an error box.
 *
 * These lived inside `routes/audiences.tsx` and were imported from there
 * by seven other modules — SmeFormDialog, messaging, messaging detail,
 * talks, smes, topics and pillars. That route is being deleted (it was
 * unreachable: no sidebar entry, no settings tile, no <Link> anywhere,
 * and it modelled AudienceProfile as a first-class entity, which the
 * data model does not), so the primitives move somewhere that is about
 * forms rather than about audiences.
 *
 * A shared component living inside a page is how a page stops being
 * deletable. Worth noticing early next time.
 */
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";


export function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | undefined;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
      {error ? <span className="text-xs text-danger">{error}</span> : null}
    </div>
  );
}


export function ListField({
  label,
  hint,
  values,
  error,
  onChange,
  onAdd,
}: {
  label: string;
  hint?: string;
  values: string[];
  error?: string | undefined;
  onChange: (index: number, value: string) => void;
  onAdd: () => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        {hint ? <span className="text-xs text-fg-subtle">{hint}</span> : null}
      </div>
      <div className="flex flex-col gap-2">
        {values.map((v, i) => (
          <Input
            key={i}
            value={v}
            onChange={(e) => onChange(i, e.currentTarget.value)}
            placeholder={`Item ${i + 1}`}
          />
        ))}
        <Button type="button" variant="ghost" size="sm" onClick={onAdd}>
          + Add item
        </Button>
      </div>
      {error ? <span className="text-xs text-danger">{error}</span> : null}
    </div>
  );
}


export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return (
    <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
      {message}
    </div>
  );
}
