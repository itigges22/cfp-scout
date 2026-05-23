/**
 * /graph — knowledge-graph exploration view (plan 21).
 *
 * Obsidian-style force-directed canvas powered by react-force-graph-2d.
 * Backend filters live on /api/v1/graph/full (plan 16/21): kinds, status,
 * since, max_nodes. Server attaches `degree` per node so the canvas can
 * size them without recomputing.
 *
 * Pass-1 surface:
 *   - Filter chips for node kinds (multi-select)
 *   - Conference-only status filter chips
 *   - "Since" date input
 *   - Click → side drawer with entity summary + link to detail page
 *   - Hover → highlight neighbors (dim non-adjacent)
 *   - Truncation banner when results > max_nodes
 *
 * Deferred to pass 2: pillar selector, "center on entity" autocomplete,
 * saved views, PNG export, Louvain community coloring.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { Suspense, lazy, useCallback, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { graphApi } from "@/lib/api";
import type { GraphLink, GraphNode, GraphNodeKind } from "@/lib/api-types";
import { EmptyState, PageHeader } from "@/routes/dashboard";

// Lazy-load the canvas — react-force-graph-2d depends on canvas APIs that
// aren't worth shipping in the initial bundle of every page.
const ForceGraph2D = lazy(async () => {
  const mod = await import("react-force-graph-2d");
  return { default: mod.default };
});

export const Route = createFileRoute("/graph")({
  component: GraphPage,
});

const KIND_LABELS: Record<GraphNodeKind, string> = {
  conference: "Conferences",
  topic: "Topics",
  sme: "SMEs",
  audience: "Audiences",
  pillar: "Pillars",
  messaging: "Messaging",
  source: "Sources",
  series: "Series",
};

const KIND_COLOR: Record<GraphNodeKind, string> = {
  conference: "#ef4444", // red
  topic: "#06b6d4",      // cyan
  sme: "#a855f7",        // violet
  audience: "#f97316",   // orange
  pillar: "#22c55e",     // green
  messaging: "#3b82f6",  // blue
  source: "#94a3b8",     // slate
  series: "#eab308",     // amber
};

const STATUS_CHOICES = [
  "approved",
  "needs_review",
  "needs_review_pillar",
  "needs_sme_review",
  "discovered",
  "low_messaging_fit",
] as const;

const DEFAULT_KINDS: GraphNodeKind[] = ["conference", "topic", "sme"];

function GraphPage() {
  const [kinds, setKinds] = useState<Set<GraphNodeKind>>(new Set(DEFAULT_KINDS));
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const [since, setSince] = useState<string>("");
  const [selected, setSelected] = useState<GraphNode | null>(null);

  const queryKey = useMemo(
    () => [
      "graph",
      "full",
      {
        kinds: [...kinds].sort(),
        status: [...statusFilter].sort(),
        since,
      },
    ],
    [kinds, statusFilter, since],
  );

  const { data, isLoading, error, refetch } = useQuery({
    queryKey,
    queryFn: () =>
      graphApi.full({
        kinds: kinds.size ? [...kinds] : undefined,
        status: statusFilter.size ? [...statusFilter] : undefined,
        ...(since ? { since } : {}),
        max_nodes: 500,
      }),
  });

  const toggleKind = (k: GraphNodeKind) => {
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const toggleStatus = (s: string) => {
    setStatusFilter((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Graph"
        description="Explore relationships between conferences, topics, SMEs, audiences, pillars."
      />

      <FilterBar
        kinds={kinds}
        statusFilter={statusFilter}
        since={since}
        onToggleKind={toggleKind}
        onToggleStatus={toggleStatus}
        onSinceChange={setSince}
        onReset={() => {
          setKinds(new Set(DEFAULT_KINDS));
          setStatusFilter(new Set());
          setSince("");
        }}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <Card className="overflow-hidden">
          <CardContent className="relative h-[640px] p-0">
            {data?.stats?.truncated ? (
              <div className="absolute left-3 top-3 z-10 rounded-md border border-warning/40 bg-warning/15 px-3 py-1.5 text-xs text-warning">
                Truncated to {data.stats.n_nodes} most-connected nodes. Narrow filters
                to see more.
              </div>
            ) : null}
            {error ? (
              <div className="flex h-full items-center justify-center text-sm text-danger">
                Failed to load graph.
              </div>
            ) : isLoading ? (
              <div className="flex h-full items-center justify-center">
                <Skeleton className="h-3/4 w-3/4 rounded-md" />
              </div>
            ) : !data || data.nodes.length === 0 ? (
              <EmptyState message="No nodes match the current filters. Try resetting or widening the date window." />
            ) : (
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center text-sm text-fg-muted">
                    Loading canvas…
                  </div>
                }
              >
                <GraphCanvas
                  nodes={data.nodes}
                  links={data.links}
                  onNodeClick={setSelected}
                />
              </Suspense>
            )}
          </CardContent>
        </Card>

        <DetailDrawer
          node={selected}
          onClose={() => setSelected(null)}
          onRefresh={() => {
            void refetch();
          }}
        />
      </div>

      <Legend />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------
function FilterBar({
  kinds,
  statusFilter,
  since,
  onToggleKind,
  onToggleStatus,
  onSinceChange,
  onReset,
}: {
  kinds: Set<GraphNodeKind>;
  statusFilter: Set<string>;
  since: string;
  onToggleKind: (k: GraphNodeKind) => void;
  onToggleStatus: (s: string) => void;
  onSinceChange: (s: string) => void;
  onReset: () => void;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-fg-subtle">
            Show kinds
          </span>
          {(Object.keys(KIND_LABELS) as GraphNodeKind[]).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => onToggleKind(k)}
              className={[
                "rounded-full border px-3 py-1 text-xs transition-colors",
                kinds.has(k)
                  ? "border-transparent text-canvas"
                  : "border-border text-fg-muted hover:border-border-strong",
              ].join(" ")}
              style={kinds.has(k) ? { backgroundColor: KIND_COLOR[k] } : undefined}
            >
              <span
                className="mr-1 inline-block h-2 w-2 rounded-full align-middle"
                style={{
                  backgroundColor: kinds.has(k)
                    ? "rgba(255,255,255,0.85)"
                    : KIND_COLOR[k],
                }}
              />
              {KIND_LABELS[k]}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-fg-subtle">
            Conference status
          </span>
          {STATUS_CHOICES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onToggleStatus(s)}
              className={[
                "rounded-full border px-3 py-1 text-xs transition-colors",
                statusFilter.has(s)
                  ? "border-accent bg-accent/15 text-accent"
                  : "border-border text-fg-muted hover:border-border-strong",
              ].join(" ")}
            >
              {s.replace(/_/g, " ")}
            </button>
          ))}
          {statusFilter.size === 0 ? (
            <span className="text-[10px] text-fg-subtle">all open</span>
          ) : null}
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label
              htmlFor="since"
              className="text-xs uppercase tracking-wider text-fg-subtle"
            >
              Start date ≥
            </Label>
            <Input
              id="since"
              type="date"
              value={since}
              onChange={(e) => onSinceChange(e.target.value)}
              className="w-44"
            />
          </div>
          <Button variant="ghost" size="sm" onClick={onReset}>
            Reset
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Canvas
// ---------------------------------------------------------------------------
function GraphCanvas({
  nodes,
  links,
  onNodeClick,
}: {
  nodes: GraphNode[];
  links: GraphLink[];
  onNodeClick: (n: GraphNode) => void;
}) {
  // Clone — the library mutates positions onto these objects.
  const graphData = useMemo(
    () => ({
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    }),
    [nodes, links],
  );

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);

  const adjacency = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const l of links) {
      const s =
        typeof l.source === "string" ? l.source : (l.source as { id: string }).id;
      const t =
        typeof l.target === "string" ? l.target : (l.target as { id: string }).id;
      if (!map.has(s)) map.set(s, new Set());
      if (!map.has(t)) map.set(t, new Set());
      map.get(s)!.add(t);
      map.get(t)!.add(s);
    }
    return map;
  }, [links]);

  const nodeIsDim = useCallback(
    (id: string): boolean => {
      if (!hoverId) return false;
      if (hoverId === id) return false;
      return !(adjacency.get(hoverId)?.has(id) ?? false);
    },
    [hoverId, adjacency],
  );

  const linkIsDim = useCallback(
    (l: GraphLink): boolean => {
      if (!hoverId) return false;
      const s =
        typeof l.source === "string" ? l.source : (l.source as { id: string }).id;
      const t =
        typeof l.target === "string" ? l.target : (l.target as { id: string }).id;
      return s !== hoverId && t !== hoverId;
    },
    [hoverId],
  );

  // Size by sqrt(degree) so hubs feel bigger without dominating.
  const sizeFor = (n: GraphNode) => 3 + Math.sqrt((n.degree ?? 1) + 1) * 1.5;

  return (
    <div ref={containerRef} className="h-full w-full">
      <ForceGraph2D
        graphData={graphData}
        nodeId="id"
        // The library reads label for default tooltips; we render our own
        // text inside nodeCanvasObject so this is just for hover tooltips.
        nodeLabel={(n: any) => `${(n as GraphNode).label} (${(n as GraphNode).kind})`}
        backgroundColor="transparent"
        cooldownTime={4000}
        d3VelocityDecay={0.3}
        linkColor={(l: any) =>
          linkIsDim(l as GraphLink) ? "rgba(148,163,184,0.12)" : "rgba(148,163,184,0.45)"
        }
        linkWidth={(l: any) =>
          Math.max(0.6, Math.min(3.0, ((l as GraphLink).weight ?? 1) * 1.2))
        }
        nodeCanvasObject={(node: any, ctx, globalScale) => {
          const n = node as GraphNode & { x: number; y: number };
          const radius = sizeFor(n);
          const baseColor = KIND_COLOR[n.kind] ?? "#94a3b8";
          const dim = nodeIsDim(n.id);
          ctx.globalAlpha = dim ? 0.25 : 1.0;

          if (hoverId === n.id) {
            ctx.beginPath();
            ctx.arc(n.x, n.y, radius + 3, 0, Math.PI * 2);
            ctx.fillStyle = baseColor + "33";
            ctx.fill();
          }
          ctx.beginPath();
          ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
          ctx.fillStyle = baseColor;
          ctx.fill();
          ctx.lineWidth = 0.75;
          ctx.strokeStyle = "rgba(15, 23, 42, 0.7)";
          ctx.stroke();

          // Label rendering: at high zoom (>1.3) or on hover. Draw a
          // semi-opaque background pill BEHIND the text so overlapping
          // labels remain readable instead of becoming smushed pixels.
          // Font size has a floor of 11px regardless of zoom.
          if (globalScale > 1.3 || hoverId === n.id) {
            const fontSize = Math.max(11, 12 / globalScale);
            ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
            const label = n.label.length > 36 ? n.label.slice(0, 35) + "…" : n.label;
            const textWidth = ctx.measureText(label).width;
            const padX = 4 / globalScale;
            const padY = 2 / globalScale;
            const boxX = n.x + radius + 2 / globalScale;
            const boxY = n.y - fontSize / 2 - padY;
            const boxH = fontSize + padY * 2;
            const boxW = textWidth + padX * 2;
            // Background pill (slate-900 at 80%).
            ctx.fillStyle = dim
              ? "rgba(15,23,42,0.45)"
              : "rgba(15,23,42,0.82)";
            ctx.beginPath();
            ctx.roundRect(boxX, boxY, boxW, boxH, 3 / globalScale);
            ctx.fill();
            // Text.
            ctx.fillStyle = dim
              ? "rgba(226,232,240,0.55)"
              : "rgba(248,250,252,0.98)";
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(label, boxX + padX, n.y);
          }
          ctx.globalAlpha = 1.0;
        }}
        onNodeHover={(n: any) => setHoverId(n ? (n as GraphNode).id : null)}
        onNodeClick={(n: any) => onNodeClick(n as GraphNode)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail drawer
// ---------------------------------------------------------------------------
function DetailDrawer({
  node,
  onClose,
  onRefresh,
}: {
  node: GraphNode | null;
  onClose: () => void;
  onRefresh: () => void;
}) {
  if (!node) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-3 py-4 text-sm text-fg-muted">
          <p className="text-xs uppercase tracking-wider text-fg-subtle">
            Inspector
          </p>
          <p>Click a node to inspect it. Hover to highlight its neighbors.</p>
          <Button variant="ghost" size="sm" onClick={onRefresh}>
            Refresh graph
          </Button>
        </CardContent>
      </Card>
    );
  }

  const id = node.id.split(":")[1];
  const isConferenceLink = node.kind === "conference" && !!id;

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-fg-subtle">
              {node.kind}
            </p>
            <h3 className="text-base font-medium">{node.label}</h3>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            ×
          </Button>
        </div>

        <KindMetadata node={node} />

        <div className="flex flex-col gap-1 pt-2 text-xs text-fg-subtle">
          <span>Degree: {node.degree ?? "?"}</span>
        </div>

        {isConferenceLink ? (
          <Link
            to="/conferences/$id"
            params={{ id: id! }}
            className="mt-2 inline-flex items-center justify-center rounded-md bg-accent px-3 py-1.5 text-sm text-accent-fg hover:opacity-90"
          >
            Open detail page →
          </Link>
        ) : null}
      </CardContent>
    </Card>
  );
}

function KindMetadata({ node }: { node: GraphNode }) {
  const rows: Array<[string, string]> = [];
  switch (node.kind) {
    case "conference":
      if (node.status) rows.push(["Status", node.status]);
      if (node.start_date) rows.push(["Start", node.start_date]);
      if (node.confidence != null)
        rows.push(["Confidence", String(Math.round(node.confidence * 100) / 100)]);
      break;
    case "sme":
      if (node.team) rows.push(["Team", node.team]);
      break;
    case "topic":
      if (node.pending_review) rows.push(["Pending", "yes"]);
      if (node.is_active === false) rows.push(["Active", "no"]);
      break;
    case "audience":
      if (node.industry) rows.push(["Industry", node.industry]);
      if (node.role_seniority) rows.push(["Seniority", node.role_seniority]);
      break;
    case "pillar":
      if (node.display_order != null)
        rows.push(["Order", String(node.display_order)]);
      break;
    case "source":
      if (node.source_kind) rows.push(["Kind", node.source_kind]);
      break;
  }
  if (rows.length === 0) {
    return (
      <p className="text-xs text-fg-muted">No additional metadata for this node.</p>
    );
  }
  return (
    <dl className="grid grid-cols-2 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-fg-subtle">{k}</dt>
          <dd className="text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------
function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
      <span className="uppercase tracking-wider text-fg-subtle">Legend</span>
      {(Object.keys(KIND_LABELS) as GraphNodeKind[]).map((k) => (
        <Badge key={k} variant="muted" className="flex items-center gap-2">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: KIND_COLOR[k] }}
          />
          {KIND_LABELS[k]}
        </Badge>
      ))}
    </div>
  );
}
