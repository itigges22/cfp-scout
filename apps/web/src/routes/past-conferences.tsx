import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { CalendarSyncImportDialog } from "@/components/past-conferences/CalendarSyncImportDialog";
import { CsvImportDialog } from "@/components/past-conferences/CsvImportDialog";
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
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.name}</TableCell>
                    <TableCell className="tabular-nums">{p.year}</TableCell>
                    <TableCell>
                      <Badge variant={p.role === "speaker" ? "accent" : "muted"}>{p.role}</Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {p.session_type ?? "—"}
                    </TableCell>
                    <TableCell className="text-fg-muted text-xs tabular-nums">
                      {p.attended_sme_ids.length}
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
    </div>
  );
}
