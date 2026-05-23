import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
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
import { messagingApi } from "@/lib/api";
import { ErrorBox } from "@/routes/audiences";
import { TeamGuidance } from "@/components/team/TeamGuidance";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/messaging")({
  component: MessagingPage,
});

const PER_PAGE = 20;

function MessagingPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);

  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["messaging", { page, q: debouncedSearch }],
    queryFn: () =>
      messagingApi.list({ page, per_page: PER_PAGE, q: debouncedSearch || undefined }),
  });
  const deactivate = useMutation({
    mutationFn: (id: string) => messagingApi.deactivate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messaging"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Messaging & positioning"
        description="Active product messaging documents. The matcher's Stage A scores every conference against these."
      />
      <TeamGuidance
        storedHere="Structured messaging documents per product / positioning (elevator pitch, key themes, talking points, differentiators, competitive position). Each one is embedded and used as the comparison corpus for conference matching."
        addInline="+ New messaging document"
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <CardTitle>Messaging documents</CardTitle>
            {query.data ? <Badge variant="muted">{query.data.total} total</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            <Input
              type="search"
              placeholder="Search by title"
              value={search}
              onChange={(e) => {
                setSearch(e.currentTarget.value);
                setPage(1);
              }}
              className="w-64"
            />
            <Link to="/messaging/new">
              <Button>New</Button>
            </Link>
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
              No messaging documents yet. The structured-entry wizard lands in the next pass; or seed via the XLSX workbook (plan 31).
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Themes</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="font-medium">{m.title}</TableCell>
                    <TableCell>
                      <Badge variant={m.source_type === "pdf" ? "accent" : "muted"}>
                        {m.source_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {m.key_themes.slice(0, 3).join(" · ")}
                      {m.key_themes.length > 3 ? "…" : null}
                    </TableCell>
                    <TableCell className="text-fg-muted text-xs tabular-nums">
                      {new Date(m.updated_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      {m.is_active ? (
                        <Badge variant="success">active</Badge>
                      ) : (
                        <Badge variant="muted">inactive</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {m.is_active ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => deactivate.mutate(m.id)}
                          disabled={deactivate.isPending}
                          aria-label={`deactivate ${m.title}`}
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
