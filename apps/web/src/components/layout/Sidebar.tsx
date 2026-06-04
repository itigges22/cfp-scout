import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  BookOpen,
  CalendarClock,
  GitFork,
  History,
  LayoutDashboard,
  Loader2,
  Plus,
  Settings,
  Users,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { ApiError, pillarsApi } from "@/lib/api";
import type { PillarRead } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const DISCOVER_PRIMARY = [
  { to: "/dashboard",    label: "Dashboard",   Icon: LayoutDashboard },
  { to: "/conferences",  label: "Conferences", Icon: CalendarClock },
  { to: "/graph",        label: "Graph",       Icon: GitFork },
] as const;

const DISCOVER_SECONDARY = [
  { to: "/past-conferences", label: "Past Events", Icon: History },
  { to: "/smes",             label: "SMEs",        Icon: Users },
  { to: "/talks",            label: "Talks",       Icon: BookOpen },
] as const;

function NavLink({
  to,
  Icon,
  children,
}: {
  to: string;
  Icon: React.ElementType;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium",
        "text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg",
      )}
      activeProps={{ className: "bg-surface-2 text-fg" }}
    >
      <Icon className="size-4" />
      {children}
    </Link>
  );
}

export function Sidebar() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;

  const [editingPillar, setEditingPillar] = useState<PillarRead | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const pillarsQuery = useQuery({
    queryKey: ["pillars"],
    queryFn: () => pillarsApi.list(),
    staleTime: 5 * 60 * 1000,
  });
  const pillars = (pillarsQuery.data ?? []).slice().sort((a, b) => a.display_order - b.display_order);

  // Delay single-click navigation so double-click can intercept it.
  const clickTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const handlePillarClick = (pillar: PillarRead) => {
    const timer = setTimeout(() => {
      void navigate({ to: "/pillars/$id", params: { id: pillar.id } });
      clickTimers.current.delete(pillar.id);
    }, 220);
    clickTimers.current.set(pillar.id, timer);
  };

  const handlePillarDoubleClick = (pillar: PillarRead) => {
    const timer = clickTimers.current.get(pillar.id);
    if (timer) {
      clearTimeout(timer);
      clickTimers.current.delete(pillar.id);
    }
    setEditingPillar(pillar);
  };

  const isPillarActive = (id: string) => currentPath === `/pillars/${id}`;

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-border bg-surface px-3 py-4">
      <Link
        to="/dashboard"
        className="mb-6 flex items-center gap-2 px-3 text-lg font-semibold tracking-tight"
      >
        <span className="text-accent">●</span>
        <span>Scout</span>
      </Link>

      <nav className="flex flex-1 flex-col gap-5 overflow-y-auto">
        {/* ---- DISCOVER ---- */}
        <div className="flex flex-col gap-0.5">
          <h2 className="mb-1 px-3 text-xs font-semibold uppercase tracking-widest text-fg-subtle">
            Discover
          </h2>
          {DISCOVER_PRIMARY.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} Icon={Icon}>{label}</NavLink>
          ))}

          <div className="mx-3 my-1.5 border-t border-border/40" />

          {DISCOVER_SECONDARY.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} Icon={Icon}>{label}</NavLink>
          ))}
        </div>

        {/* ---- INFO (pillars) ---- */}
        <div className="flex flex-col gap-0.5">
          <h2 className="mb-1 px-3 text-xs font-semibold uppercase tracking-widest text-fg-subtle">
            Info
          </h2>

          {pillars.map((pillar) => (
            <div
              key={pillar.id}
              role="button"
              tabIndex={0}
              title="Click to open · double-click to edit"
              onClick={() => handlePillarClick(pillar)}
              onDoubleClick={() => handlePillarDoubleClick(pillar)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handlePillarClick(pillar);
              }}
              className={cn(
                "flex cursor-pointer select-none items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium",
                "text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg",
                isPillarActive(pillar.id) && "bg-surface-2 text-fg",
              )}
            >
              <span className="flex size-4 shrink-0 items-center justify-center text-xs font-bold text-accent">
                ◆
              </span>
              <span className="truncate">{pillar.name}</span>
            </div>
          ))}

          <button
            onClick={() => setShowCreate(true)}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium",
              "text-fg-subtle transition-colors hover:bg-surface-2 hover:text-fg",
            )}
          >
            <Plus className="size-3.5" />
            Add pillar
          </button>
        </div>
      </nav>

      {/* ---- Settings pinned to bottom ---- */}
      <div className="mt-2 border-t border-border/40 pt-2">
        <Link
          to="/settings"
          className={cn(
            "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium",
            "text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg",
          )}
          activeProps={{ className: "bg-surface-2 text-fg" }}
        >
          <Settings className="size-4" />
          Settings
        </Link>
      </div>

      <PillarEditDialog
        pillar={editingPillar}
        onClose={() => setEditingPillar(null)}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["pillars"] });
          setEditingPillar(null);
        }}
      />

      <PillarCreateDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onSaved={(newId) => {
          void qc.invalidateQueries({ queryKey: ["pillars"] });
          setShowCreate(false);
          void navigate({ to: "/pillars/$id", params: { id: newId } });
        }}
      />
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Edit dialog
// ---------------------------------------------------------------------------

function PillarEditDialog({
  pillar,
  onClose,
  onSaved,
}: {
  pillar: PillarRead | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (pillar) {
      setName(pillar.name);
      setDescription(pillar.description);
      setError(null);
    }
  }, [pillar]);

  const save = useMutation({
    mutationFn: () =>
      pillarsApi.update(pillar!.id, { name: name.trim(), description: description.trim() }),
    onSuccess: onSaved,
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Failed to save."),
  });

  return (
    <Dialog open={pillar !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit pillar</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <div className="flex flex-col gap-1.5">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.currentTarget.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.currentTarget.value)}
              rows={4}
            />
          </div>
          {error && (
            <p className="rounded border border-danger/30 bg-danger/10 p-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={save.isPending || !name.trim()}
          >
            {save.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Create dialog
// ---------------------------------------------------------------------------

function PillarCreateDialog({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (newId: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setError(null);
    }
  }, [open]);

  const create = useMutation({
    mutationFn: () =>
      pillarsApi.create({ name: name.trim(), description: description.trim() }),
    onSuccess: (data) => onSaved(data.id),
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Failed to create."),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New pillar</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <div className="flex flex-col gap-1.5">
            <Label>Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              placeholder="e.g. Platform Engineering"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.currentTarget.value)}
              placeholder="What is this pillar about?"
              rows={4}
            />
          </div>
          {error && (
            <p className="rounded border border-danger/30 bg-danger/10 p-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            disabled={create.isPending || !name.trim() || !description.trim()}
          >
            {create.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
