/**
 * Status pill — colored Badge variant per conferences.status.
 * Used in list rows + detail header.
 */

import { Badge } from "@/components/ui/badge";

const VARIANT_FOR_STATUS: Record<
  string,
  React.ComponentProps<typeof Badge>["variant"]
> = {
  approved: "success",
  needs_review: "warning",
  needs_review_pillar: "warning",
  needs_sme_review: "warning",
  discovered: "muted",
  rejected: "danger",
  low_messaging_fit: "muted",
  quarantined: "danger",
};

const LABELS: Record<string, string> = {
  approved: "Approved",
  needs_review: "Needs review",
  needs_review_pillar: "Needs pillar review",
  needs_sme_review: "Needs SME review",
  discovered: "Discovered",
  rejected: "Rejected",
  low_messaging_fit: "Low messaging fit",
  quarantined: "Quarantined",
};

export function StatusPill({ status }: { status: string }) {
  const variant = VARIANT_FOR_STATUS[status] ?? "muted";
  const label = LABELS[status] ?? status;
  return <Badge variant={variant}>{label}</Badge>;
}
