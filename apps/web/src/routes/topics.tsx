import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { EyeOff } from "lucide-react";
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
import { topicsApi } from "@/lib/api";
import { ErrorBox } from "@/routes/audiences";
import { PageBanner, PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/topics")({
  component: TopicsPage,
});

const PER_PAGE = 50;
type Filter = "active" | "inactive" | "all";

function TopicsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [filter, setFilter] = useState<Filter>("active");

  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["topics", { page, q: debouncedSearch, filter }],
    queryFn: () =>
      topicsApi.list({
        page,
        per_page: PER_PAGE,
        q: debouncedSearch || undefined,
        // pending_only=false shows only approved/active; null shows all
        pending_only: filter === "active" ? false : filter === "inactive" ? null : null,
      }),
  });

  const deactivate = useMutation({
    mutationFn: (id: string) => topicsApi.reject(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["topics"] }),
  });

  const activeTopics =
    filter === "inactive"
      ? (query.data?.items ?? []).filter((t) => !t.is_active)
      : filter === "active"
        ? (query.data?.items ?? []).filter((t) => t.is_active && !t.pending_review)
        : (query.data?.items ?? []);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Topic vocabulary"
        description="Topics extracted from conference pages and used for SME matching."
      />

      <PageBanner>
        When the scraper processes a conference, the LLM pulls out topic strings (e.g. "MLOps,"
        "vector databases," "RAG") and adds them to this vocabulary automatically. Noise terms like
        "registration" or "networking" are filtered out before they land here.{" "}
        <strong>Active topics count in matching</strong> — the SME topic-overlap dimension (30% of
        the SME score) uses this list. If a topic slips through that shouldn't be here, hit the
        deactivate button and add the term to the noise blocklist in{" "}
        <strong>Settings → Tunables → Talks library</strong>.
      </PageBanner>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <CardTitle>Topics</CardTitle>
            {query.data ? <Badge variant="muted">{query.data.total} total</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            <FilterTabs value={filter} onChange={(f) => { setFilter(f); setPage(1); }} />
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
          ) : activeTopics.length === 0 ? (
            <div className="rounded-md border border-dashed border-border-strong bg-surface-2 py-10 text-center text-sm text-fg-muted">
              No topics in this filter.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Aliases</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeTopics.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.name}</TableCell>
                    <TableCell className="font-mono text-xs text-fg-muted">{t.slug}</TableCell>
                    <TableCell className="text-xs text-fg-muted">
                      {t.aliases.length > 0 ? t.aliases.join(", ") : "—"}
                    </TableCell>
                    <TableCell>
                      {t.pending_review ? (
                        <Badge variant="warning">legacy pending</Badge>
                      ) : t.is_active ? (
                        <Badge variant="success">active</Badge>
                      ) : (
                        <Badge variant="muted">inactive</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {t.is_active ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => deactivate.mutate(t.id)}
                          disabled={deactivate.isPending}
                          title="Deactivate — removes from matching"
                          aria-label={`deactivate ${t.name}`}
                        >
                          <EyeOff className="size-4 text-fg-subtle hover:text-danger" />
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

function FilterTabs({
  value,
  onChange,
}: {
  value: Filter;
  onChange: (next: Filter) => void;
}) {
  const tabs: { value: Filter; label: string }[] = [
    { value: "active", label: "Active" },
    { value: "inactive", label: "Inactive" },
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
