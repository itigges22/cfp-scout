import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { CalendarSyncImportDialog } from "@/components/past-conferences/CalendarSyncImportDialog";
import { CsvImportDialog } from "@/components/past-conferences/CsvImportDialog";
import { PastConferenceEditDialog } from "@/components/past-conferences/PastConferenceEditDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { pastConferencesApi } from "@/lib/api";
import { ErrorBox } from "@/routes/audiences";
import { TeamGuidance } from "@/components/team/TeamGuidance";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/past-conferences")({
  component: PastConferencesPage,
});

const PER_PAGE = 20;

function PastConferencesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [yearFilter, setYearFilter] = useState<string>("");
  const [showImport, setShowImport] = useState(false);
  const [showCalendarSync, setShowCalendarSync] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<
    import("@/lib/api-types").PastConferenceRead | null
  >(null);

  const qc = useQueryClient();
  const deleteMut = useMutation({
    mutationFn: (id: string) => pastConferencesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["past-conferences"] }),
  });

  // Verdict mutation with optimistic update — the row's verdict
  // changes instantly in the UI, then sync to the server in the
  // background. The conferences list will reflect the change on
  // next render (live boost recompute, no rescore needed).
  const verdictMut = useMutation({
    mutationFn: ({
      id,
      verdict,
    }: {
      id: string;
      verdict: import("@/lib/api-types").PastConferenceVerdict;
    }) => pastConferencesApi.setVerdict(id, verdict),
    onMutate: async ({ id, verdict }) => {
      // Optimistic: patch the cached past-conferences list so the
      // button highlights immediately. If the server PATCH fails,
      // onError reverts.
      const keys = qc.getQueryCache().findAll({ queryKey: ["past-conferences"] });
      const snapshots: Array<{ key: readonly unknown[]; data: unknown }> = [];
      for (const k of keys) {
        const prev = qc.getQueryData<{
          items: Array<{ id: string; verdict: string }>;
        }>(k.queryKey);
        if (prev) {
          snapshots.push({ key: k.queryKey, data: prev });
          qc.setQueryData(k.queryKey, {
            ...prev,
            items: prev.items.map((it) =>
              it.id === id ? { ...it, verdict } : it,
            ),
          });
        }
      }
      return { snapshots };
    },
    onError: (_err, _vars, ctx) => {
      // Revert all snapshots if server rejected.
      for (const s of ctx?.snapshots ?? []) {
        qc.setQueryData(s.key, s.data);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["past-conferences"] });
      // Also invalidate the upcoming-conferences list so its
      // overall_score reorders to reflect the new verdict.
      qc.invalidateQueries({ queryKey: ["conferences"] });
    },
  });

  const yearAsNum = /^\d{4}$/.test(yearFilter) ? Number(yearFilter) : undefined;

  const query = useQuery({
    queryKey: ["past-conferences", { page, q: debouncedSearch, year: yearAsNum }],
    queryFn: () =>
      pastConferencesApi.list({
        page,
        per_page: PER_PAGE,
        q: debouncedSearch || undefined,
        year: yearAsNum,
      }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Past events"
        description="History of who on the team attended what. Powers the past-attendance signal in the SME ranker."
      />
      <TeamGuidance
        storedHere="One row per (event, year) the team attended in the past, with the SMEs who went, role (speaker / sponsor / attendee), session type, and free-form notes. The SME ranker uses this for the 'has-attended-this-series-before' boost."
        addInline="+ New past event"
        workbookSheet="PastConferences"
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <CardTitle>Past conferences</CardTitle>
            {query.data ? <Badge variant="muted">{query.data.total} total</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            <Input
              type="search"
              placeholder="Search by name"
              value={search}
              onChange={(e) => {
                setSearch(e.currentTarget.value);
                setPage(1);
              }}
              className="w-56"
            />
            <Input
              type="text"
              placeholder="Year"
              value={yearFilter}
              onChange={(e) => {
                setYearFilter(e.currentTarget.value);
                setPage(1);
              }}
              className="w-24"
              maxLength={4}
            />
            <Button variant="outline" onClick={() => setShowCreate(true)}>
              <Plus className="mr-1 size-4" />
              New
            </Button>
            <Button variant="outline" onClick={() => setShowImport(true)}>
              Import CSV
            </Button>
            <Button onClick={() => setShowCalendarSync(true)}>
              Import calendar sync
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {query.isLoading ? (
            <div className="flex flex-col gap-2 py-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : query.isError ? (
            <ErrorBox error={query.error} />
          ) : query.data === undefined || query.data.items.length === 0 ? (
            <div className="rounded-md border border-dashed border-border-strong bg-surface-2 py-10 text-center text-sm text-fg-muted">
              No past conferences recorded yet. Bulk-seed via the XLSX workbook (plan 31), or the
              CSV import drop-zone lands in the next pass.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Conference</TableHead>
                  <TableHead>Year</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Session</TableHead>
                  <TableHead>Attendees</TableHead>
                  <TableHead
                    className="text-center"
                    title="Was attending this worth it? Drives the matcher's series_memory boost on similar upcoming events. Updates take effect on the next /conferences page load — no rescore needed."
                  >
                    Worth it?
                  </TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((p) => (
                  <TableRow
                    key={p.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setEditing(p)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setEditing(p);
                      }
                    }}
                    className="cursor-pointer hover:bg-surface-2"
                  >
                    <TableCell className="font-medium">{p.name}</TableCell>
                    <TableCell className="tabular-nums">{p.year}</TableCell>
                    <TableCell>
                      <Badge variant={p.role === "speaker" ? "accent" : "muted"}>{p.role}</Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {p.session_type ?? "—"}
                    </TableCell>
                    <TableCell className="text-fg-muted text-xs">
                      {p.attended_by_names_raw && p.attended_by_names_raw.length > 0 ? (
                        <span title={p.attended_by_names_raw.join(", ")}>
                          {p.attended_by_names_raw.slice(0, 3).join(", ")}
                          {p.attended_by_names_raw.length > 3
                            ? ` +${p.attended_by_names_raw.length - 3}`
                            : ""}
                          {p.attended_sme_ids.length === 0 ? (
                            <span
                              className="ml-1 text-warning"
                              title="None of these names are linked to an active SME yet. Add the people on /smes and edit this row to link them."
                            >
                              ⚠
                            </span>
                          ) : (
                            <span className="ml-1 text-fg-subtle tabular-nums">
                              ({p.attended_sme_ids.length} linked)
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-fg-subtle">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-center">
                      <VerdictPicker
                        current={p.verdict}
                        onChange={(verdict) =>
                          verdictMut.mutate({ id: p.id, verdict })
                        }
                        disabled={verdictMut.isPending}
                      />
                    </TableCell>
                    <TableCell>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (
                            window.confirm(
                              `Delete "${p.name}" (${p.year})? This removes the row + its audit trail. Cannot be undone.`,
                            )
                          ) {
                            deleteMut.mutate(p.id);
                          }
                        }}
                        disabled={deleteMut.isPending}
                        aria-label={`delete ${p.name}`}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {query.data ? (
            <Pagination
              page={page}
              perPage={PER_PAGE}
              total={query.data.total}
              onPageChange={setPage}
            />
          ) : null}
        </CardContent>
      </Card>

      <CsvImportDialog open={showImport} onOpenChange={setShowImport} />
      <CalendarSyncImportDialog
        open={showCalendarSync}
        onOpenChange={setShowCalendarSync}
      />
      <PastConferenceEditDialog
        open={showCreate}
        initial={null}
        onOpenChange={setShowCreate}
      />
      <PastConferenceEditDialog
        open={editing !== null}
        initial={editing}
        onOpenChange={(o) => {
          if (!o) setEditing(null);
        }}
      />
    </div>
  );
}

/**
 * Three-button toggle: 👍 / — / 👎 mapping to ``would_attend`` /
 * ``unsure`` / ``would_not_attend``. Clicking the currently-selected
 * button flips back to ``unsure`` so the operator can "unset" a
 * verdict without leaving the page.
 *
 * Stops click propagation so clicking a button doesn't bubble up
 * to the TableRow's onClick (which opens the edit dialog).
 */
function VerdictPicker({
  current,
  onChange,
  disabled,
}: {
  current: import("@/lib/api-types").PastConferenceVerdict;
  onChange: (v: import("@/lib/api-types").PastConferenceVerdict) => void;
  disabled: boolean;
}) {
  const opts: Array<{
    value: import("@/lib/api-types").PastConferenceVerdict;
    label: string;
    title: string;
    active: string;
  }> = [
    {
      value: "would_attend",
      label: "👍",
      title: "Would attend again — boosts similar upcoming events by +0.10.",
      active: "bg-success/20 ring-1 ring-success/40",
    },
    {
      value: "unsure",
      label: "—",
      title: "No verdict yet — small +0.05 nudge on similar upcoming events.",
      active: "bg-surface-3 ring-1 ring-border-strong",
    },
    {
      value: "would_not_attend",
      label: "👎",
      title: "Would NOT attend again — penalty of −0.10 on similar upcoming events.",
      active: "bg-danger/20 ring-1 ring-danger/40",
    },
  ];
  return (
    <div className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
      {opts.map((opt) => {
        const isActive = current === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            title={opt.title}
            disabled={disabled}
            onClick={(e) => {
              e.stopPropagation();
              // Click the currently-active button to clear to "unsure".
              onChange(isActive && opt.value !== "unsure" ? "unsure" : opt.value);
            }}
            className={
              "size-7 rounded text-sm leading-none transition-colors hover:bg-surface-2 " +
              (isActive ? opt.active : "text-fg-muted")
            }
            aria-pressed={isActive}
            aria-label={opt.title}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
