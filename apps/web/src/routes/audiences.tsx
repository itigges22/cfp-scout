import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Pagination } from "@/components/Pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { ApiError, audiencesApi } from "@/lib/api";
import type {
  AudienceProfileCreate,
  AudienceProfileRead,
  RoleSeniority,
} from "@/lib/api-types";
import { TeamGuidance } from "@/components/team/TeamGuidance";
import { PageHeader } from "@/routes/dashboard";

export const Route = createFileRoute("/audiences")({
  component: AudiencesPage,
});

const PER_PAGE = 20;
const ROLE_SENIORITY_OPTIONS: RoleSeniority[] = [
  "executive",
  "director",
  "manager",
  "ic",
  "mixed",
];

function AudiencesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [showCreate, setShowCreate] = useState(false);
  // null = dialog closed; AudienceProfileRead = edit that one
  const [editing, setEditing] = useState<AudienceProfileRead | null>(null);

  const query = useQuery({
    queryKey: ["audiences", { page, q: debouncedSearch }],
    queryFn: () =>
      audiencesApi.list({ page, per_page: PER_PAGE, q: debouncedSearch || undefined }),
  });

  const queryClient = useQueryClient();
  const deactivate = useMutation({
    mutationFn: (id: string) => audiencesApi.deactivate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["audiences"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audiences"
        description="<vendor> personas. Used by the matcher to predict which conference attendees the team is trying to reach."
      />
      <TeamGuidance
        storedHere="The 11 <vendor> audience personas (C-Suite, App Dev ITDM, Data Scientist, …) with their pain points, key messages, and exclusion criteria. The SME ranker uses these to compute SME ↔ audience overlap; the matcher uses them when scoring conference fit."
        addInline="+ New audience"
        workbookSheet="Audiences"
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-3">
            <CardTitle>Audience profiles</CardTitle>
            {query.data ? (
              <Badge variant="muted">{query.data.total} total</Badge>
            ) : null}
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
              className="w-64"
            />
            <Button onClick={() => setShowCreate(true)}>
              <Plus className="size-4" />
              New
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
            <EmptyAudiences />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Industry</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Key messages</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((a) => (
                  <TableRow
                    key={a.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setEditing(a)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setEditing(a);
                      }
                    }}
                    className="cursor-pointer hover:bg-surface-2"
                  >
                    <TableCell className="font-medium">{a.name}</TableCell>
                    <TableCell className="text-fg-muted">{a.industry}</TableCell>
                    <TableCell>
                      <Badge variant="muted">{a.role_seniority}</Badge>
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {a.key_messages.slice(0, 2).join(" · ")}
                      {a.key_messages.length > 2 ? "…" : null}
                    </TableCell>
                    <TableCell>
                      {a.is_active ? (
                        <Badge variant="success">active</Badge>
                      ) : (
                        <Badge variant="muted">inactive</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {a.is_active ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            deactivate.mutate(a.id);
                          }}
                          disabled={deactivate.isPending}
                          aria-label={`deactivate ${a.name}`}
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

      <AudienceDialog
        open={showCreate}
        initial={null}
        onOpenChange={setShowCreate}
      />
      <AudienceDialog
        open={editing !== null}
        initial={editing}
        onOpenChange={(o) => {
          if (!o) setEditing(null);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audience form — works for both create AND edit. Pass `initial` to edit an
// existing row, or null to create a new one. Same dialog component is mounted
// twice from AudiencesPage; React unmounts the unused one cleanly.
// ---------------------------------------------------------------------------
const EMPTY_AUDIENCE: AudienceProfileCreate = {
  name: "",
  description: "",
  industry: "",
  role_seniority: "ic",
  primary_pain_points: ["", ""],
  key_messages: ["", ""],
  exclusion_criteria: [],
  is_active: true,
};

function AudienceDialog({
  open,
  initial,
  onOpenChange,
}: {
  open: boolean;
  initial: AudienceProfileRead | null;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const isEdit = initial !== null;
  const [form, setForm] = useState<AudienceProfileCreate>(EMPTY_AUDIENCE);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Re-seed the form when the dialog opens with a different row (or
  // transitions create ↔ edit). Pads list fields to at least two slots so
  // the ListField always shows somewhere to type a new item.
  useEffect(() => {
    if (!open) return;
    if (initial) {
      const pad = (xs: string[]) =>
        xs.length >= 2 ? xs : [...xs, ...Array(2 - xs.length).fill("")];
      setForm({
        name: initial.name,
        description: initial.description,
        industry: initial.industry,
        role_seniority: initial.role_seniority,
        primary_pain_points: pad(initial.primary_pain_points),
        key_messages: pad(initial.key_messages),
        exclusion_criteria: initial.exclusion_criteria,
        is_active: initial.is_active,
      });
    } else {
      setForm(EMPTY_AUDIENCE);
    }
    setFieldErrors({});
  }, [open, initial]);

  const mutate = useMutation({
    mutationFn: (body: AudienceProfileCreate) => {
      const cleaned = {
        ...body,
        primary_pain_points: body.primary_pain_points.filter((s) => s.trim().length > 0),
        key_messages: body.key_messages.filter((s) => s.trim().length > 0),
        exclusion_criteria: body.exclusion_criteria.filter((s) => s.trim().length > 0),
      };
      return isEdit && initial
        ? audiencesApi.update(initial.id, cleaned)
        : audiencesApi.create(cleaned);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["audiences"] });
      onOpenChange(false);
    },
    onError: (err) => {
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors());
    },
  });

  const updateList =
    (field: "primary_pain_points" | "key_messages") => (index: number, value: string) => {
      setForm((prev) => {
        const next = [...prev[field]];
        next[index] = value;
        return { ...prev, [field]: next };
      });
    };

  const addListItem = (field: "primary_pain_points" | "key_messages") => () =>
    setForm((prev) => ({ ...prev, [field]: [...prev[field], ""] }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit "${initial?.name}"` : "New audience profile"}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <Field label="Name" error={fieldErrors.name}>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
              placeholder="Platform Engineering Lead"
            />
          </Field>
          <Field label="Description" error={fieldErrors.description}>
            <Textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.currentTarget.value })}
              placeholder="50–500 chars. Who is this persona, what do they care about?"
              rows={3}
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Industry" error={fieldErrors.industry}>
              <Input
                value={form.industry}
                onChange={(e) => setForm({ ...form, industry: e.currentTarget.value })}
                placeholder="Financial Services"
              />
            </Field>
            <Field label="Role seniority" error={fieldErrors.role_seniority}>
              <select
                className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm"
                value={form.role_seniority}
                onChange={(e) =>
                  setForm({ ...form, role_seniority: e.currentTarget.value as RoleSeniority })
                }
              >
                {ROLE_SENIORITY_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <ListField
            label="Primary pain points"
            hint="2–8 items, 10–200 chars each"
            values={form.primary_pain_points}
            error={fieldErrors.primary_pain_points}
            onChange={updateList("primary_pain_points")}
            onAdd={addListItem("primary_pain_points")}
          />
          <ListField
            label="Key messages"
            hint="2–8 items"
            values={form.key_messages}
            error={fieldErrors.key_messages}
            onChange={updateList("key_messages")}
            onAdd={addListItem("key_messages")}
          />

          {mutate.isError && mutate.error instanceof ApiError && Object.keys(fieldErrors).length === 0 ? (
            <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
              {mutate.error.message}
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={mutate.isPending}
          >
            Cancel
          </Button>
          <Button onClick={() => mutate.mutate(form)} disabled={mutate.isPending}>
            {mutate.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            {isEdit ? "Save changes" : "Create audience"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Small shared helpers (exported so the other list pages can reuse)
// ---------------------------------------------------------------------------
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

function EmptyAudiences() {
  return (
    <div className="rounded-md border border-dashed border-border-strong bg-surface-2 py-10 text-center text-sm text-fg-muted">
      No audiences yet. Click <strong>New</strong> to create one, or bulk-seed via the XLSX
      workbook (plan 31).
    </div>
  );
}
