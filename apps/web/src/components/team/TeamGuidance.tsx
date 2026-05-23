/**
 * Small "what is this page for, where does the data come from"
 * explainer that lives at the top of each Team-section page.
 *
 * User feedback (sidebar overhaul round): "The Team sidebar makes no
 * sense ... it's confusing where data is stored / located and how to
 * give it more information about team members, strategy, messaging
 * and positioning, events we have attended, etc."
 *
 * Each Team page now drops one of these in directly under its
 * PageHeader. Two-column layout: what's stored here (left) + how to
 * add more (right). Same component, different content per page —
 * keeps the explanation visible without taking over the screen.
 */

import { Link } from "@tanstack/react-router";
import { ArrowRight, Upload } from "lucide-react";

export function TeamGuidance({
  storedHere,
  addInline,
  workbookSheet,
}: {
  /** One sentence — what this page stores + what the matcher uses it for. */
  storedHere: string;
  /** Label of the inline create affordance (e.g. "+ New SME"). */
  addInline?: string;
  /** Sheet name in the workbook (e.g. "SMEs", "Audiences"). */
  workbookSheet?: string;
}) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-2 p-3 text-sm">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between md:gap-6">
        <p className="flex-1 text-fg">
          <span className="text-xs uppercase tracking-wider text-fg-muted">
            What lives here
          </span>
          <br />
          {storedHere}
        </p>
        <div className="flex-1 text-fg">
          <span className="text-xs uppercase tracking-wider text-fg-muted">
            How to add more
          </span>
          <ul className="mt-0.5 space-y-0.5 text-xs text-fg-muted">
            {addInline && (
              <li className="flex items-center gap-1">
                <ArrowRight className="h-3 w-3" />
                Inline: use the <strong className="text-fg">{addInline}</strong>{" "}
                button on this page.
              </li>
            )}
            {workbookSheet && (
              <li className="flex items-center gap-1">
                <Upload className="h-3 w-3" />
                Bulk: edit the{" "}
                <strong className="text-fg">{workbookSheet}</strong> sheet in
                the workbook, then{" "}
                <Link to="/settings" className="text-accent hover:underline">
                  upload it from Settings
                </Link>
                .
              </li>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
}
