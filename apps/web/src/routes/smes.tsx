import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { Pagination } from "@/components/Pagination";
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
import { smesApi } from "@/lib/api";
import { ErrorBox } from "@/routes/audiences";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/smes")({
  component: SmesPage,
});

const PER_PAGE = 20;
type TeamFilter = "all" | "daam" | "non-daam";

function SmesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");

  const queryClient = useQueryClient();
  const teamParam = teamFilter === "daam" ? "team" : undefined;
  const query = useQuery({
    queryKey: ["smes", { page, q: debouncedSearch, teamFilter }],
    queryFn: () =>
      smesApi.list({
        page,
        per_page: PER_PAGE,
        q: debouncedSearch || undefined,
        team: teamParam,
      }),
    // Non-team filter is harder server-side (NOT match) — we'll fetch all and
    // filter client-side for now. Cheap because the SME table stays small.
    select: (data) =>
      teamFilter === "non-daam"
        ? { ...data, items: data.items.filter((s) => s.team !== "team") }
        : data,
  });
  const deactivate = useMutation({
    mutationFn: (id: string) => smesApi.deactivate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["smes"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="SMEs"
        description="team and Non-team subject-matter experts. Profiles drive the matcher."
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
            <Button disabled title="SME form lands next">New</Button>
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
              No SMEs yet. Bulk-seed via the XLSX workbook (plan 31) or add via the form (next pass).
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
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">{s.full_name}</TableCell>
                    <TableCell>
                      <Badge variant={s.team === "team" ? "accent" : "muted"}>{s.team}</Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {s.expertise_areas.slice(0, 3).join(" · ")}
                      {s.expertise_areas.length > 3 ? "…" : null}
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
                      {s.is_active ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => deactivate.mutate(s.id)}
                          disabled={deactivate.isPending}
                          aria-label={`deactivate ${s.full_name}`}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      ) : null}
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
    { value: "daam", label: "team" },
    { value: "non-daam", label: "Non-team" },
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
