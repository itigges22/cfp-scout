import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Check, X } from "lucide-react";
import { useState } from "react";

import { Pagination } from "@/components/Pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { topicsApi } from "@/lib/api";
import { ErrorBox } from "@/routes/audiences";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/topics")({
  component: TopicsPage,
});

const PER_PAGE = 50;
type Filter = "pending" | "approved" | "all";

function TopicsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [filter, setFilter] = useState<Filter>("pending");

  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["topics", { page, q: debouncedSearch, filter }],
    queryFn: () =>
      topicsApi.list({
        page,
        per_page: PER_PAGE,
        q: debouncedSearch || undefined,
        pending_only: filter === "pending" ? true : filter === "approved" ? false : null,
      }),
  });
  const approve = useMutation({
    mutationFn: (id: string) => topicsApi.approve(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["topics"] }),
  });
  const reject = useMutation({
    mutationFn: (id: string) => topicsApi.reject(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["topics"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Topics"
        description="Controlled vocabulary. New topics discovered by the LLM extractor stay in the pending queue until you approve them — they don't influence matching while pending."
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">How this works</CardTitle>
          <CardDescription>
            Pending topics are LLM-discovered from scraped conference pages (plan 15). Approving
            adds them to the active vocabulary and lets the matcher use them. Rejecting deactivates
            them — they stay in the DB for audit but never appear in dropdowns or influence matching.
          </CardDescription>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <CardTitle>Topic vocabulary</CardTitle>
            {query.data ? <Badge variant="muted">{query.data.total} total</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            <FilterTabs value={filter} onChange={setFilter} />
            <Input
              type="search"
              placeholder="Search"
              value={search}
              onChange={(e) => {
                setSearch(e.currentTarget.value);
                setPage(1);
              }}
              className="w-56"
            />
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
              {filter === "pending"
                ? "No pending topics. The LLM extractor in plan 15 populates this queue."
                : "No topics in this filter."}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Aliases</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-24" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.name}</TableCell>
                    <TableCell className="text-fg-muted font-mono text-xs">{t.slug}</TableCell>
                    <TableCell className="text-fg-muted text-xs">
                      {t.aliases.length > 0 ? t.aliases.join(", ") : "—"}
                    </TableCell>
                    <TableCell>
                      {t.pending_review ? (
                        <Badge variant="warning">pending review</Badge>
                      ) : t.is_active ? (
                        <Badge variant="success">active</Badge>
                      ) : (
                        <Badge variant="muted">inactive</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {t.pending_review ? (
                        <div className="flex items-center gap-1">
                          <Button
                            size="icon"
                            variant="ghost"
                            onClick={() => approve.mutate(t.id)}
                            disabled={approve.isPending || reject.isPending}
                            title="Approve"
                            aria-label={`approve ${t.name}`}
                          >
                            <Check className="size-4 text-success" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            onClick={() => reject.mutate(t.id)}
                            disabled={approve.isPending || reject.isPending}
                            title="Reject"
                            aria-label={`reject ${t.name}`}
                          >
                            <X className="size-4 text-danger" />
                          </Button>
                        </div>
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

function FilterTabs({
  value,
  onChange,
}: {
  value: Filter;
  onChange: (next: Filter) => void;
}) {
  const tabs: { value: Filter; label: string }[] = [
    { value: "pending", label: "Pending" },
    { value: "approved", label: "Approved" },
    { value: "all", label: "All" },
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
