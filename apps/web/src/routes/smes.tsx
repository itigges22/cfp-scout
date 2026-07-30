import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { BarChart3, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { SmeFormDialog } from "@/components/sme/SmeFormDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { smesApi } from "@/lib/api";
import { ErrorBox } from "@/components/form";
import { TeamGuidance } from "@/components/team/TeamGuidance";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/smes")({
  component: SmesPage,
});

const PER_PAGE = 20;
type TeamFilter = "all" | "primary" | "other";

function SmesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");
  const [showCreate, setShowCreate] = useState(false);
  // Deactivating used to leave the row sitting in the list looking much like
  // the others, so it read as "nothing happened". Deactivated SMEs are hidden
  // by default now — the row visibly leaves — and this toggle brings them
  // back so nothing is unrecoverable.
  const [showInactive, setShowInactive] = useState(false);
  // null = nothing being edited; SmeRead = open the edit dialog
  const [perfSme, setPerfSme] = useState<{ id: string; name: string } | null>(null);
  const [editing, setEditing] = useState<import("@/lib/api-types").SmeRead | null>(null);

  const queryClient = useQueryClient();
  // Both tabs are answered by the server now. The "other teams" tab used to
  // fetch a page and drop non-matching rows from it, so the count shown and
  // the pages after the first were both wrong.
  const externalOnly =
    teamFilter === "other" ? true : teamFilter === "primary" ? false : undefined;
  const query = useQuery({
    queryKey: ["smes", { page, q: debouncedSearch, teamFilter, showInactive }],
    queryFn: () =>
      smesApi.list({
        page,
        per_page: PER_PAGE,
        q: debouncedSearch || undefined,
        external_only: externalOnly,
        ...(showInactive ? {} : { is_active: true }),
      }),
  });
  // Deactivate is reversible, so the row needs both actions. Before this the
  // trash button was hidden once is_active went false, which left the row
  // permanently stranded in the list with nothing you could do to it.
  const restore = useMutation({
    mutationFn: (sme: import("@/lib/api-types").SmeRead) => smesApi.restore(sme),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["smes"] }),
  });
  const deactivate = useMutation({
    mutationFn: (id: string) => smesApi.deactivate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["smes"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="SMEs"
        description="Subject-matter experts. Their bio, topics and audience focus drive the speaker half of every conference score."
      />
      <TeamGuidance
        storedHere="SMEs (your team and beyond) with their expertise areas, primary topics, audience focus, location, and bio. Bio similarity, topic overlap, and audience overlap all feed the per-conference SME ranker."
        addInline="+ New SME"
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <CardTitle>SME directory</CardTitle>
            {query.data ? <Badge variant="muted">{query.data.total} total</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            <TeamTabs value={teamFilter} onChange={setTeamFilter} />
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
            <label className="flex items-center gap-1.5 text-xs text-fg-muted">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => {
                  setShowInactive(e.currentTarget.checked);
                  setPage(1);
                }}
              />
              Show deactivated
            </label>
            <Button onClick={() => setShowCreate(true)}>New SME</Button>
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
              No SMEs yet. Add one with the New button above.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Team</TableHead>
                  <TableHead>Expertise</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((s) => (
                  <TableRow
                    key={s.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setEditing(s)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setEditing(s);
                      }
                    }}
                    className="cursor-pointer hover:bg-surface-2"
                  >
                    <TableCell className="font-medium">{s.full_name}</TableCell>
                    <TableCell>
                      <Badge variant={s.team === "team" ? "accent" : "muted"}>{s.team}</Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {(s.expertise ?? "").trim().length > 0 ? "✓ described" : "—"}
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {[s.location_city, s.location_country].filter(Boolean).join(", ") ||
                        s.location_country}
                    </TableCell>
                    <TableCell>
                      {s.is_active ? (
                        <Badge variant="success">active</Badge>
                      ) : (
                        <Badge variant="muted">inactive</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          setPerfSme({ id: s.id, name: s.full_name });
                        }}
                        aria-label={`performance of ${s.full_name}`}
                        title="Performance"
                      >
                        <BarChart3 className="size-4" />
                      </Button>
                      {s.is_active ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            // The row disappears from the default view, so
                            // say so before doing it rather than after.
                            if (
                              window.confirm(
                                `Deactivate ${s.full_name}? They stop being matched to conferences and leave this list. ` +
                                  `Tick "Show deactivated" to bring them back.`,
                              )
                            ) {
                              deactivate.mutate(s.id);
                            }
                          }}
                          disabled={deactivate.isPending}
                          aria-label={`deactivate ${s.full_name}`}
                          title="Deactivate"
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            restore.mutate(s);
                          }}
                          disabled={restore.isPending}
                          aria-label={`restore ${s.full_name}`}
                          title="Restore"
                        >
                          <RotateCcw className="mr-1 size-4" />
                          Restore
                        </Button>
                      )}
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

      <SmeFormDialog open={showCreate} onOpenChange={setShowCreate} />
      <SmeFormDialog
        open={editing !== null}
        initial={editing}
        onOpenChange={(o) => {
          if (!o) setEditing(null);
        }}
      />
      {perfSme ? (
        <SmePerformanceDialog sme={perfSme} onClose={() => setPerfSme(null)} />
      ) : null}
    </div>
  );
}

// All numbers computed server-side by /smes/{id}/analytics — this dialog
// only renders. The spend/leads shown are EVENT-level outcomes of
// conferences this person attended, not a personal budget.
function SmePerformanceDialog({
  sme,
  onClose,
}: {
  sme: { id: string; name: string };
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["smes", sme.id, "analytics"],
    queryFn: () => smesApi.analytics(sme.id),
  });

  const verdictLabel: Record<string, string> = {
    would_attend: "Would attend again",
    unsure: "Unsure",
    would_not_attend: "Would not attend again",
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{sme.name} — performance</DialogTitle>
        </DialogHeader>
        {q.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : q.isError || !q.data ? (
          <p className="text-sm text-danger">Could not load analytics.</p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MiniPerf label="Events" value={q.data.events_total} />
              <MiniPerf label="Attended" value={q.data.events_attended} />
              <MiniPerf label="Upcoming" value={q.data.events_upcoming} />
              <MiniPerf
                label="Talks given"
                value={
                  q.data.events.filter((e) => e.activity === "talk" && e.attended)
                    .length
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <MiniPerf
                label="Spend at attended events"
                value={`$${q.data.attended_events_spend_usd.toLocaleString()}`}
              />
              <MiniPerf
                label="Leads from attended events"
                value={q.data.attended_events_leads}
              />
            </div>
            {Object.keys(q.data.by_activity).length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {Object.entries(q.data.by_activity).map(([a, n]) => (
                  <Badge key={a} variant="muted">
                    {a}: {n}
                  </Badge>
                ))}
              </div>
            ) : null}
            {q.data.events.length === 0 ? (
              <p className="text-sm text-fg-muted">
                No participation recorded yet. Add {sme.name} under "Who is
                going" on a conference page to start tracking.
              </p>
            ) : (
              <ul className="max-h-64 space-y-1.5 overflow-y-auto">
                {q.data.events.map((e) => (
                  <li
                    key={`${e.conference_id}-${e.activity}`}
                    className="flex items-center justify-between gap-3 rounded-md border border-border-subtle bg-surface-2 px-3 py-2 text-sm"
                  >
                    <span className="truncate">
                      {e.conference_name}
                      <span className="ml-2 text-xs text-fg-muted">
                        {e.activity}
                        {e.start_date ? ` · ${e.start_date}` : ""}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs text-fg-muted">
                      {e.attended
                        ? e.attendance_verdict
                          ? (verdictLabel[e.attendance_verdict] ?? e.attendance_verdict)
                          : "attended"
                        : "planned"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function MiniPerf({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border-subtle bg-surface-2 px-3 py-2.5">
      <p className="text-xs text-fg-muted">{label}</p>
      <p className="text-xl font-bold tabular-nums">{value}</p>
    </div>
  );
}

function TeamTabs({
  value,
  onChange,
}: {
  value: TeamFilter;
  onChange: (next: TeamFilter) => void;
}) {
  const tabs: { value: TeamFilter; label: string }[] = [
    { value: "all", label: "All" },
    { value: "primary", label: "My team" },
    { value: "other", label: "Other" },
  ];
  return (
    <div className="inline-flex rounded-md border border-border bg-surface p-0.5">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          onClick={() => onChange(t.value)}
          className={
            value === t.value
              ? "rounded-sm bg-surface-2 px-3 py-1 text-xs font-medium"
              : "rounded-sm px-3 py-1 text-xs font-medium text-fg-muted hover:text-fg"
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
