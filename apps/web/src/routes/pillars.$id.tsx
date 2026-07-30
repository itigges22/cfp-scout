import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { FileText, Loader2, Plus, Trash2, Upload, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useUnsavedWorkWarning } from "@/hooks/useUnsavedWorkWarning";
import { formatDate } from "@/lib/utils";
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
import { SmeFormDialog } from "@/components/sme/SmeFormDialog";
import { StatusPill } from "@/components/conferences/StatusPill";
import { ApiError, audiencesApi, messagingApi, pillarsApi, smesApi, talksApi } from "@/lib/api";
import type {
  AudienceProfileCreate,
  AudienceProfileRead,
  DocKind,
  MessagingDocUploadPreview,
  MessagingDocumentCreate,
  MessagingDocumentRead,
  PillarRead,
  RoleSeniority,
  SmePillarRead,
  SmeRead,
  TalkRead,
} from "@/lib/api-types";
import { PageHeader } from "@/routes/dashboard";
import { ErrorBox, Field, ListField } from "@/components/form";

export const Route = createFileRoute("/pillars/$id")({
  component: PillarDetailPage,
});

type Tab = "overview" | "talks" | "smes" | "audiences" | "roadmap" | "gtm";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "talks", label: "Talks" },
  { id: "smes", label: "SMEs" },
  { id: "audiences", label: "Audiences" },
  { id: "roadmap", label: "Content Roadmap" },
  { id: "gtm", label: "GTM Strategy" },
];

const REVIEW_STATUS_VARIANT: Record<string, "muted" | "accent" | "warning"> = {
  draft: "muted",
  pending_review: "warning",
  approved: "accent",
};

const ROLE_SENIORITY_OPTIONS: RoleSeniority[] = [
  "executive", "director", "manager", "ic", "mixed",
];

function PillarDetailPage() {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [showEdit, setShowEdit] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const pillarQuery = useQuery({
    queryKey: ["pillars", id],
    queryFn: () => pillarsApi.get(id),
  });
  const pillar = pillarQuery.data;

  const deletePillar = useMutation({
    mutationFn: () => pillarsApi.delete(id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["pillars"] });
      void navigate({ to: "/dashboard" });
    },
  });

  if (pillarQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!pillar) {
    return (
      <div className="rounded-md border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
        Pillar not found.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <PageHeader title={pillar.name} description={pillar.description} />
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowEdit(true)}>
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-danger hover:bg-danger/10 hover:text-danger"
            onClick={() => setShowDeleteConfirm(true)}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>

      {/* Stats row */}
      <div className="flex gap-6 text-sm">
        {[
          { label: "SMEs", value: pillar.sme_count },
          { label: "Talks", value: pillar.talk_count },
          { label: "Audiences", value: pillar.audience_count },
        ].map((s) => (
          <div key={s.label} className="flex items-center gap-1.5 text-fg-muted">
            <span className="font-semibold text-fg">{s.value}</span>
            <span>{s.label}</span>
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={[
              "px-4 py-2 text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "border-b-2 border-accent text-accent"
                : "text-fg-muted hover:text-fg",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "overview" && <OverviewTab pillar={pillar} />}
      {activeTab === "talks" && <TalksTab pillarId={id} />}
      {activeTab === "smes" && <SmesTab pillarId={id} />}
      {activeTab === "audiences" && <AudiencesTab pillarId={id} />}
      {activeTab === "roadmap" && <RoadmapTab pillarId={id} />}
      {activeTab === "gtm" && <GtmTab pillarId={id} />}

      {/* Edit pillar dialog */}
      <PillarEditDialog
        pillar={showEdit ? pillar : null}
        onClose={() => setShowEdit(false)}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["pillars"] });
          setShowEdit(false);
        }}
      />

      {/* Delete confirmation */}
      <Dialog open={showDeleteConfirm} onOpenChange={(o) => !o && setShowDeleteConfirm(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete "{pillar.name}"?</DialogTitle>
          </DialogHeader>
          <p className="px-6 text-sm text-fg-muted">
            This will permanently remove the pillar and unlink all associated SMEs, talks, and
            audiences. This cannot be undone.
          </p>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setShowDeleteConfirm(false)}
              disabled={deletePillar.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="ghost"
              className="text-danger hover:bg-danger/10 hover:text-danger"
              onClick={() => deletePillar.mutate()}
              disabled={deletePillar.isPending}
            >
              {deletePillar.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
              Delete pillar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

function OverviewTab({ pillar }: { pillar: PillarRead }) {
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Description</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-fg-muted leading-relaxed">
            {pillar.description || "No description."}
          </p>
        </CardContent>
      </Card>
      {pillar.enriched_description ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">AI-enriched description</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-fg-muted leading-relaxed">
              {pillar.enriched_description.slice(0, 600)}
              {pillar.enriched_description.length > 600 ? "…" : ""}
            </p>
          </CardContent>
        </Card>
      ) : null}
      <PerformanceCard pillarId={pillar.id} />
      <TopConferencesCard pillarId={pillar.id} />
    </div>
  );
}

// All numbers computed server-side by /pillars/{id}/analytics from the
// "who is going" rows + per-conference outcome fields — this component
// only renders. NOTE the attribution rule: a conference aligned to two
// pillars counts toward both, so never total these across pillars.
function PerformanceCard({ pillarId }: { pillarId: string }) {
  const q = useQuery({
    queryKey: ["pillars", pillarId, "analytics"],
    queryFn: () => pillarsApi.analytics(pillarId),
  });

  if (q.isLoading) {
    return (
      <Card className="col-span-full">
        <CardContent className="py-6">
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (q.isError || !q.data) return null;
  const a = q.data;

  const verdictLabel: Record<string, string> = {
    would_attend: "Would attend again",
    unsure: "Unsure",
    would_not_attend: "Would not attend again",
  };

  return (
    <Card className="col-span-full">
      <CardHeader>
        <CardTitle className="text-sm">Performance</CardTitle>
        <p className="mt-1 text-xs text-fg-muted">
          From attendance tracking on conferences aligned to this pillar.
        </p>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <PerfStat label="Aligned conferences" value={a.conferences_aligned} />
          <PerfStat label="Attended" value={a.conferences_attended} />
          <PerfStat label="Planned" value={a.conferences_planned} />
          <PerfStat label="Total spend" value={`$${a.spend_usd_total.toLocaleString()}`} />
          <PerfStat label="Leads" value={a.leads_total} />
          <PerfStat
            label="Cost per lead"
            value={a.cost_per_lead_usd != null ? `$${a.cost_per_lead_usd}` : "—"}
          />
        </div>
        {Object.keys(a.verdicts).length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(a.verdicts).map(([v, n]) => (
              <span
                key={v}
                className="rounded-full border border-border bg-surface-2 px-3 py-1 text-xs text-fg-muted"
              >
                {verdictLabel[v] ?? v}: {n}
              </span>
            ))}
          </div>
        ) : null}
        {a.attended.length > 0 ? (
          <div className="mt-4 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Conference</TableHead>
                  <TableHead className="text-right">People</TableHead>
                  <TableHead className="text-right">Spend</TableHead>
                  <TableHead className="text-right">Leads</TableHead>
                  <TableHead>Worth it?</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {a.attended.map((r) => (
                  <TableRow key={r.conference_id}>
                    <TableCell className="font-medium">{r.conference_name}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.n_people}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.spend_usd != null ? `$${r.spend_usd.toLocaleString()}` : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.leads_generated ?? "—"}
                    </TableCell>
                    <TableCell className="text-fg-muted">
                      {r.attendance_verdict ? (verdictLabel[r.attendance_verdict] ?? r.attendance_verdict) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-fg-muted">
            No attended conferences recorded yet — mark people as attended on a
            conference page and fill in "How it went" to populate this.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function PerfStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border-subtle bg-surface-2 px-3 py-2.5">
      <p className="text-xs text-fg-muted">{label}</p>
      <p className="text-xl font-bold tabular-nums">{value}</p>
    </div>
  );
}

// Ranked by the matcher's per-pillar alignment edge (conference_pillars),
// not by top-pillar assignment — so a conference relevant to two pillars
// shows up on both pages, each with its own ordering.
function TopConferencesCard({ pillarId }: { pillarId: string }) {
  const q = useQuery({
    queryKey: ["pillars", pillarId, "conferences"],
    queryFn: () => pillarsApi.listConferences(pillarId),
  });

  return (
    <Card className="col-span-full">
      <CardHeader>
        <CardTitle className="text-sm">Top conferences for this pillar</CardTitle>
        <p className="mt-1 text-xs text-fg-muted">
          Ranked by how well each conference matches this pillar specifically.
          Overall is the same blended score the conference pages show.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        {q.isLoading ? (
          <div className="p-6">
            <Skeleton className="h-32 w-full" />
          </div>
        ) : q.isError ? (
          <div className="p-6">
            <ErrorBox error={q.error} />
          </div>
        ) : (q.data ?? []).length === 0 ? (
          <p className="p-6 text-sm text-fg-muted">
            No scored conferences align with this pillar yet. Run the matcher
            after adding messaging or pillar content.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Conference</TableHead>
                <TableHead className="text-right">Pillar fit</TableHead>
                <TableHead className="text-right">Overall</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Starts</TableHead>
                <TableHead>CFP closes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(q.data ?? []).map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">
                    <Link
                      to="/conferences/$id"
                      params={{ id: c.id }}
                      className="hover:underline"
                    >
                      {c.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {Math.round(c.pillar_score * 100)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {c.overall_score != null ? Math.round(c.overall_score * 100) : "—"}
                  </TableCell>
                  <TableCell>
                    <StatusPill status={c.status} />
                  </TableCell>
                  <TableCell className="text-fg-muted">
                    {c.start_date ? formatDate(c.start_date) : "—"}
                  </TableCell>
                  <TableCell className="text-fg-muted">
                    {c.cfp_close_at ? formatDate(c.cfp_close_at) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Talks
// ---------------------------------------------------------------------------

function TalksTab({ pillarId }: { pillarId: string }) {
  const q = useQuery({
    queryKey: ["talks", { pillar_id: pillarId }],
    queryFn: () => talksApi.list({ pillar_id: pillarId, per_page: 100 }),
  });

  if (q.isLoading) return <Skeleton className="h-40 w-full" />;
  if (q.isError) return <ErrorBox error={q.error} />;

  const talks: TalkRead[] = q.data?.items ?? [];

  if (talks.length === 0) {
    return (
      <EmptyState>
        No talks assigned to this pillar. Go to the{" "}
        <span className="font-medium text-fg">Talks Library</span> and set the pillar when
        creating or editing a talk.
      </EmptyState>
    );
  }

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Format</TableHead>
              <TableHead>Submissions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {talks.map((talk) => (
              <TableRow key={talk.id}>
                <TableCell className="font-medium">{talk.title}</TableCell>
                <TableCell>
                  <Badge variant={REVIEW_STATUS_VARIANT[talk.review_status] ?? "muted"}>
                    {talk.review_status.replace("_", " ")}
                  </Badge>
                </TableCell>
                <TableCell className="text-fg-muted">{talk.talk_format ?? "—"}</TableCell>
                <TableCell>{talk.submissions.length}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// SMEs
// ---------------------------------------------------------------------------

function SmesTab({ pillarId }: { pillarId: string }) {
  const qc = useQueryClient();
  const [showLink, setShowLink] = useState(false);
  const [showCreateSme, setShowCreateSme] = useState(false);

  const pillarSmesQ = useQuery({
    queryKey: ["pillars", pillarId, "smes"],
    queryFn: () => pillarsApi.listSmes(pillarId),
  });
  const allSmesQ = useQuery({
    queryKey: ["smes", { is_active: true }],
    queryFn: () => smesApi.list({ per_page: 200, is_active: true }),
  });

  const unlink = useMutation({
    mutationFn: (smeId: string) => pillarsApi.unlinkSme(pillarId, smeId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pillars", pillarId, "smes"] });
      // The SME directory shows pillar links too.
      void qc.invalidateQueries({ queryKey: ["smes"] });
    },
  });

  if (pillarSmesQ.isLoading || allSmesQ.isLoading) return <Skeleton className="h-40 w-full" />;
  if (pillarSmesQ.isError) return <ErrorBox error={pillarSmesQ.error} />;

  const links: SmePillarRead[] = pillarSmesQ.data ?? [];
  const allSmes: SmeRead[] = allSmesQ.data?.items ?? [];
  const smeById = new Map(allSmes.map((s) => [s.id, s]));
  const linkedIds = new Set(links.map((l) => l.sme_id));

  return (
    <div className="flex flex-col gap-4">
      {/* Two actions, because there are two situations: the person already
          exists (link them) or they do not (create them, already attached to
          this pillar). Creating used to live on a separate top-level page,
          which meant leaving the pillar to add someone to it. */}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => setShowLink(true)}>
          <Plus className="mr-2 size-4" />
          Link existing
        </Button>
        <Button size="sm" onClick={() => setShowCreateSme(true)}>
          <Plus className="mr-2 size-4" />
          New SME
        </Button>
      </div>

      {links.length === 0 ? (
        <EmptyState>No SMEs linked to this pillar yet.</EmptyState>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Team</TableHead>
                  <TableHead>Primary</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {links.map((link) => {
                  const sme = smeById.get(link.sme_id);
                  return (
                    <TableRow key={link.sme_id}>
                      <TableCell className="font-medium">
                        {sme?.full_name ?? link.sme_id}
                      </TableCell>
                      <TableCell className="text-fg-muted">{sme?.team ?? "—"}</TableCell>
                      <TableCell>
                        {link.is_primary ? (
                          <Badge variant="accent">primary</Badge>
                        ) : (
                          <Badge variant="muted">—</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => unlink.mutate(link.sme_id)}
                          disabled={unlink.isPending}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <SmeFormDialog
        open={showCreateSme}
        onOpenChange={setShowCreateSme}
        defaultPillarId={pillarId}
      />

      <LinkSmeDialog
        open={showLink}
        pillarId={pillarId}
        availableSmes={allSmes.filter((s) => !linkedIds.has(s.id))}
        onClose={() => setShowLink(false)}
        onLinked={() => {
          void qc.invalidateQueries({ queryKey: ["pillars", pillarId, "smes"] });
          setShowLink(false);
        }}
      />
    </div>
  );
}

function LinkSmeDialog({
  open,
  pillarId,
  availableSmes,
  onClose,
  onLinked,
}: {
  open: boolean;
  pillarId: string;
  availableSmes: SmeRead[];
  onClose: () => void;
  onLinked: () => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) { setSelectedId(""); setIsPrimary(false); setError(null); }
  }, [open]);

  const link = useMutation({
    mutationFn: () => pillarsApi.linkSme(pillarId, selectedId, { is_primary: isPrimary }),
    onSuccess: onLinked,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to link SME."),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Link SME to pillar</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <Field label="SME">
            <select
              className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm"
              value={selectedId}
              onChange={(e) => setSelectedId(e.currentTarget.value)}
            >
              <option value="">— select —</option>
              {availableSmes.map((s) => (
                <option key={s.id} value={s.id}>{s.full_name} ({s.team})</option>
              ))}
            </select>
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isPrimary} onChange={(e) => setIsPrimary(e.currentTarget.checked)} />
            Mark as primary pillar for this SME
          </label>
          {error && <p className="text-sm text-danger">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={link.isPending}>Cancel</Button>
          <Button onClick={() => link.mutate()} disabled={link.isPending || !selectedId}>
            {link.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Link
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Audiences — full CRUD, scoped to this pillar
// ---------------------------------------------------------------------------

const EMPTY_AUDIENCE: AudienceProfileCreate = {
  name: "",
  description: "",
  industry: "",
  role_seniority: "ic",
  primary_pain_points: ["", ""],
  key_messages: ["", ""],
  exclusion_criteria: [],
  pillar_id: null,
  is_active: true,
};

function AudiencesTab({ pillarId }: { pillarId: string }) {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<AudienceProfileRead | null>(null);

  const q = useQuery({
    // Scoped QUERY key — this list is one pillar's audiences. Invalidations
    // below use the bare ["audiences"] prefix, which still matches this.
    queryKey: ["audiences", { pillar_id: pillarId }],
    queryFn: () => audiencesApi.list({ per_page: 100, pillar_id: pillarId }),
  });

  // Deactivate is reversible; without this the row was stranded inactive
  // with no action available at all.
  const restoreAudience = useMutation({
    mutationFn: (a: AudienceProfileRead) => audiencesApi.restore(a),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["audiences"] }),
  });
  const deactivate = useMutation({
    mutationFn: (id: string) => audiencesApi.deactivate(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["audiences"] }),
  });

  if (q.isLoading) return <Skeleton className="h-40 w-full" />;
  if (q.isError) return <ErrorBox error={q.error} />;

  const audiences: AudienceProfileRead[] = q.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-2 size-4" />
          New audience
        </Button>
      </div>

      {audiences.length === 0 ? (
        <EmptyState>
          No audience profiles for this pillar yet. Click <strong>New audience</strong> to create
          one.
        </EmptyState>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Industry</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {audiences.map((a) => (
                  <TableRow
                    key={a.id}
                    role="button"
                    tabIndex={0}
                    className="cursor-pointer hover:bg-surface-2"
                    onClick={() => setEditing(a)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setEditing(a); } }}
                  >
                    <TableCell className="font-medium">{a.name}</TableCell>
                    <TableCell className="text-fg-muted">{a.industry}</TableCell>
                    <TableCell><Badge variant="muted">{a.role_seniority}</Badge></TableCell>
                    <TableCell>
                      {a.is_active
                        ? <Badge variant="success">active</Badge>
                        : <Badge variant="muted">inactive</Badge>}
                    </TableCell>
                    <TableCell>
                      {a.is_active ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={(e) => { e.stopPropagation(); deactivate.mutate(a.id); }}
                          disabled={deactivate.isPending}
                          title="Deactivate"
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => { e.stopPropagation(); restoreAudience.mutate(a); }}
                          disabled={restoreAudience.isPending}
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
          </CardContent>
        </Card>
      )}

      <AudienceDialog
        open={showCreate}
        initial={null}
        pillarId={pillarId}
        onOpenChange={(o) => { if (!o) setShowCreate(false); }}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["audiences"] });
          void qc.invalidateQueries({ queryKey: ["pillars"] });
          setShowCreate(false);
        }}
      />
      <AudienceDialog
        open={editing !== null}
        initial={editing}
        pillarId={pillarId}
        onOpenChange={(o) => { if (!o) setEditing(null); }}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["audiences"] });
          setEditing(null);
        }}
      />
    </div>
  );
}

function AudienceDialog({
  open,
  initial,
  pillarId,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  initial: AudienceProfileRead | null;
  pillarId: string;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const isEdit = initial !== null;
  const [form, setForm] = useState<AudienceProfileCreate>({ ...EMPTY_AUDIENCE, pillar_id: pillarId });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    if (initial) {
      const pad = (xs: string[]) => xs.length >= 2 ? xs : [...xs, ...Array(2 - xs.length).fill("")];
      setForm({
        name: initial.name,
        description: initial.description,
        industry: initial.industry,
        role_seniority: initial.role_seniority,
        primary_pain_points: pad(initial.primary_pain_points),
        key_messages: pad(initial.key_messages),
        exclusion_criteria: initial.exclusion_criteria,
        pillar_id: pillarId,
        is_active: initial.is_active,
      });
    } else {
      setForm({ ...EMPTY_AUDIENCE, pillar_id: pillarId });
    }
    setFieldErrors({});
  }, [open, initial, pillarId]);

  const mutate = useMutation({
    mutationFn: (body: AudienceProfileCreate) => {
      const cleaned = {
        ...body,
        primary_pain_points: body.primary_pain_points.filter((s) => s.trim()),
        key_messages: body.key_messages.filter((s) => s.trim()),
        exclusion_criteria: body.exclusion_criteria.filter((s) => s.trim()),
        pillar_id: pillarId,
      };
      return isEdit && initial
        ? audiencesApi.update(initial.id, cleaned)
        : audiencesApi.create(cleaned);
    },
    onSuccess: onSaved,
    onError: (err) => { if (err instanceof ApiError) setFieldErrors(err.fieldErrors()); },
  });

  const updateList = (field: "primary_pain_points" | "key_messages") => (index: number, value: string) =>
    setForm((prev) => { const next = [...prev[field]]; next[index] = value; return { ...prev, [field]: next }; });
  const addListItem = (field: "primary_pain_points" | "key_messages") => () =>
    setForm((prev) => ({ ...prev, [field]: [...prev[field], ""] }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit "${initial?.name}"` : "New audience profile"}</DialogTitle>
        </DialogHeader>
        <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto p-6">
          <Field label="Name" error={fieldErrors.name}>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.currentTarget.value })} placeholder="Platform Engineering Lead" />
          </Field>
          <Field label="Description" error={fieldErrors.description}>
            <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.currentTarget.value })} rows={3} />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Industry" error={fieldErrors.industry}>
              <Input value={form.industry} onChange={(e) => setForm({ ...form, industry: e.currentTarget.value })} placeholder="Financial Services" />
            </Field>
            <Field label="Role seniority" error={fieldErrors.role_seniority}>
              <select className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm" value={form.role_seniority} onChange={(e) => setForm({ ...form, role_seniority: e.currentTarget.value as RoleSeniority })}>
                {ROLE_SENIORITY_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
              </select>
            </Field>
          </div>
          <ListField label="Primary pain points" hint="2–8 items" values={form.primary_pain_points} error={fieldErrors.primary_pain_points} onChange={updateList("primary_pain_points")} onAdd={addListItem("primary_pain_points")} />
          <ListField label="Key messages" hint="2–8 items" values={form.key_messages} error={fieldErrors.key_messages} onChange={updateList("key_messages")} onAdd={addListItem("key_messages")} />
          {mutate.isError && mutate.error instanceof ApiError && Object.keys(fieldErrors).length === 0 ? (
            <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">{mutate.error.message}</div>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutate.isPending}>Cancel</Button>
          <Button onClick={() => mutate.mutate(form)} disabled={mutate.isPending}>
            {mutate.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
            {isEdit ? "Save changes" : "Create audience"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Content Roadmap + GTM Strategy — unified PDF upload tab
// ---------------------------------------------------------------------------

function RoadmapTab({ pillarId }: { pillarId: string }) {
  return <PillarDocTab pillarId={pillarId} docKind="content_roadmap" />;
}

function GtmTab({ pillarId }: { pillarId: string }) {
  return <PillarDocTab pillarId={pillarId} docKind="gtm_strategy" />;
}

const DOC_KIND_LABEL: Record<DocKind, string> = {
  gtm_strategy: "GTM Strategy",
  content_roadmap: "Content Roadmap",
  other: "Document",
};


/** Human names for the save-schema fields, for readable validation errors. */
const FIELD_LABELS: Record<string, string> = {
  title: "Title",
  elevator_pitch: "Elevator pitch",
  target_personas: "Target personas",
  key_themes: "Key themes",
  talking_points: "Talking points",
  differentiators: "Differentiators",
  competitive_position: "Competitive position",
};

/** "One or more fields failed validation" is useless — say which and why. */
function describeSaveError(err: unknown): string {
  if (err instanceof ApiError) {
    const fields = Object.entries(err.fieldErrors());
    if (fields.length) {
      return fields
        .map(([k, msg]) => `${FIELD_LABELS[k.split(".")[0] ?? k] ?? k}: ${msg}`)
        .join(" · ");
    }
    return err.message;
  }
  return String((err as Error).message);
}

type UploadPhase = "idle" | "extracting" | "review" | "saving";

function PillarDocTab({ pillarId, docKind }: { pillarId: string; docKind: DocKind }) {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [draft, setDraft] = useState<MessagingDocUploadPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const label = DOC_KIND_LABEL[docKind];
  // Nothing is persisted until the review is confirmed, so a refresh during
  // extraction or review silently discards everything. Intercept it.
  useUnsavedWorkWarning(phase !== "idle");

  const q = useQuery({
    // Scoped QUERY key; bare ["messaging"] invalidations still match it.
    queryKey: ["messaging", { pillar_id: pillarId, doc_kind: docKind }],
    queryFn: () => messagingApi.list({ pillar_id: pillarId, per_page: 50 }),
  });

  const deactivate = useMutation({
    mutationFn: (id: string) => messagingApi.deactivate(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["messaging"] }),
  });

  const extractMut = useMutation({
    mutationFn: (file: File) => messagingApi.uploadPreview(file, docKind),
    onSuccess: (data) => { setDraft(data); setPhase("review"); setError(null); },
    onError: (err) => { setError(String((err as Error).message)); setPhase("idle"); },
  });

  const saveMut = useMutation({
    mutationFn: (body: MessagingDocumentCreate) => messagingApi.create(body, "ui_admin"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["messaging"] });
      setPhase("idle");
      setDraft(null);
      setError(null);
    },
    onError: (err) => { setError(describeSaveError(err)); setPhase("review"); },
  });

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setPhase("extracting");
    extractMut.mutate(file);
    e.target.value = "";
  }

  function handleSave() {
    if (!draft) return;
    const body: MessagingDocumentCreate = {
      title: draft.title || `${label} — ${new Date().toLocaleDateString()}`,
      source_type: "pdf",
      doc_kind: docKind,
      elevator_pitch: draft.elevator_pitch || "No elevator pitch extracted.",
      target_personas: draft.target_personas.length ? draft.target_personas : ["General audience"],
      key_themes: draft.key_themes.length >= 3
        ? draft.key_themes
        : [...draft.key_themes, ...Array(3 - draft.key_themes.length).fill("To be defined")],
      talking_points: draft.talking_points.length >= 3
        ? draft.talking_points
        : [...draft.talking_points, ...Array(3 - draft.talking_points.length).fill("To be defined")],
      differentiators: draft.differentiators,
      competitive_position: draft.competitive_position,
      pillar_id: pillarId,
      is_active: true,
    };
    setPhase("saving");
    saveMut.mutate(body);
  }

  const docs = (q.data?.items ?? []).filter((d) => d.doc_kind === docKind);

  if (phase === "review" || phase === "saving") {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Review extracted fields</h3>
          <button
            type="button"
            className="text-xs text-fg-muted underline hover:text-fg"
            onClick={() => { setPhase("idle"); setDraft(null); setError(null); }}
          >
            ← Cancel
          </button>
        </div>
        <p className="text-sm text-fg-muted">
          Review what the LLM extracted from your PDF. Edit any field before saving.
        </p>

        {draft && <DocReviewForm draft={draft} onChange={setDraft} />}

        {error && (
          <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">{error}</div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => { setPhase("idle"); setDraft(null); }}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={phase === "saving"}>
            {phase === "saving" ? "Saving…" : `Save ${label}`}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-fg-muted">
          Upload a PDF to extract and store {label} content. The extracted fields are used by the matcher.
        </p>
        <div className="flex shrink-0 items-center gap-2">
          {phase === "extracting" && (
            <span className="flex items-center gap-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-1.5 text-xs text-warning">
              <Loader2 className="size-3.5 animate-spin" />
              Reading the PDF and extracting fields — typically 20–60 seconds.
              Stay on this page: nothing is saved until you review.
            </span>
          )}
          <Button
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={phase === "extracting"}
          >
            <Upload className="mr-1.5 size-4" />
            Upload PDF
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={handleFile}
          />
        </div>
      </div>

      {error && (
        <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">{error}</div>
      )}

      {q.isLoading && <Skeleton className="h-40 w-full" />}
      {q.isError && <ErrorBox error={q.error} />}

      {!q.isLoading && docs.length === 0 && (
        <EmptyState>
          No {label} uploaded yet.{" "}
          <button
            type="button"
            className="underline hover:text-fg"
            onClick={() => fileInputRef.current?.click()}
          >
            Upload a PDF
          </button>{" "}
          to get started.
        </EmptyState>
      )}

      {docs.length > 0 && (
        <div className="flex flex-col gap-3">
          {docs.map((doc, idx) => (
            <DocCard
              key={doc.id}
              doc={doc}
              badge={idx === 0 ? "current" : undefined}
              onDeactivate={() => deactivate.mutate(doc.id)}
              deactivating={deactivate.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DocCard({
  doc,
  badge,
  onDeactivate,
  deactivating,
}: {
  doc: MessagingDocumentRead;
  badge?: string;
  onDeactivate: () => void;
  deactivating: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <div className="flex items-center gap-2">
          <FileText className="size-4 text-fg-muted" />
          <CardTitle className="text-sm">{doc.title}</CardTitle>
          {badge && <Badge variant="accent">{badge}</Badge>}
          {!doc.is_active && <Badge variant="muted">inactive</Badge>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-fg-subtle">{formatDate(doc.updated_at)}</span>
          <button
            type="button"
            className="text-xs text-fg-muted underline hover:text-fg"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Hide" : "Show"}
          </button>
          {doc.is_active && (
            <Button size="icon" variant="ghost" onClick={onDeactivate} disabled={deactivating}>
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="flex flex-col gap-3 pt-0 text-sm">
          {doc.elevator_pitch && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-fg-muted mb-1">Elevator pitch</p>
              <p className="text-fg-muted leading-relaxed">{doc.elevator_pitch}</p>
            </div>
          )}
          {doc.key_themes.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-fg-muted mb-1">Key themes</p>
              <div className="flex flex-wrap gap-1.5">
                {doc.key_themes.map((t) => <Badge key={t} variant="muted">{t}</Badge>)}
              </div>
            </div>
          )}
          {doc.talking_points.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-fg-muted mb-1">Talking points</p>
              <ul className="list-disc pl-4 space-y-1 text-fg-muted">
                {doc.talking_points.map((tp, i) => <li key={i}>{tp}</li>)}
              </ul>
            </div>
          )}
          {doc.differentiators.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-fg-muted mb-1">Differentiators</p>
              <ul className="list-disc pl-4 space-y-1 text-fg-muted">
                {doc.differentiators.map((d, i) => <li key={i}>{d}</li>)}
              </ul>
            </div>
          )}
          {doc.competitive_position && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-fg-muted mb-1">Competitive position</p>
              <p className="text-fg-muted">{doc.competitive_position}</p>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function DocReviewForm({
  draft,
  onChange,
}: {
  draft: MessagingDocUploadPreview;
  onChange: (d: MessagingDocUploadPreview) => void;
}) {
  function set<K extends keyof MessagingDocUploadPreview>(key: K, value: MessagingDocUploadPreview[K]) {
    onChange({ ...draft, [key]: value });
  }

  function listArea(
    key: keyof Pick<MessagingDocUploadPreview, "target_personas" | "key_themes" | "talking_points" | "differentiators">,
    label: string,
    hint: string,
  ) {
    const arr = draft[key] as string[];
    return (
      <div className="flex flex-col gap-1">
        <Label className="font-medium">{label}</Label>
        <p className="text-xs text-fg-muted">{hint}</p>
        <textarea
          value={arr.join("\n")}
          onChange={(e) =>
            set(key, e.currentTarget.value.split(/\n+/).map((s) => s.trim()).filter(Boolean) as typeof arr)
          }
          rows={Math.max(3, arr.length + 1)}
          className="resize-y rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs"
          placeholder="One item per line"
        />
      </div>
    );
  }

  return (
    <div className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto rounded-md border border-border p-4">
      <div className="flex flex-col gap-1">
        <Label className="font-medium">Title</Label>
        <Input value={draft.title} onChange={(e) => set("title", e.currentTarget.value)} />
      </div>
      <div className="flex flex-col gap-1">
        <Label className="font-medium">Elevator pitch</Label>
        <p className="text-xs text-fg-muted">2-4 sentences. Min 50 characters.</p>
        <textarea
          value={draft.elevator_pitch}
          onChange={(e) => set("elevator_pitch", e.currentTarget.value)}
          rows={3}
          className="resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm"
        />
      </div>
      {listArea("target_personas", "Target personas", "Job titles or audience segments. One per line.")}
      {listArea("key_themes", "Key themes", "Topic areas matched against conference vocabulary. One per line. (min 3)")}
      {listArea("talking_points", "Talking points", "Specific proof points or messages. One per line. (min 3)")}
      {listArea("differentiators", "Differentiators", "What makes this distinct. One per line.")}
      <div className="flex flex-col gap-1">
        <Label className="font-medium">Competitive position</Label>
        <textarea
          value={draft.competitive_position}
          onChange={(e) => set("competitive_position", e.currentTarget.value)}
          rows={2}
          className="resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Optional"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pillar edit dialog
// ---------------------------------------------------------------------------

function PillarEditDialog({ pillar, onClose, onSaved }: { pillar: PillarRead | null; onClose: () => void; onSaved: () => void; }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (pillar) { setName(pillar.name); setDescription(pillar.description); setError(null); }
  }, [pillar]);

  const save = useMutation({
    mutationFn: () => pillarsApi.update(pillar!.id, { name: name.trim(), description: description.trim() }),
    onSuccess: onSaved,
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to save."),
  });

  return (
    <Dialog open={pillar !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Edit pillar</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <div className="flex flex-col gap-1.5">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.currentTarget.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Description</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.currentTarget.value)} rows={4} />
          </div>
          {error && <p className="rounded border border-danger/30 bg-danger/10 p-2 text-sm text-danger">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
            {save.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-sm text-fg-muted">
      {children}
    </div>
  );
}
