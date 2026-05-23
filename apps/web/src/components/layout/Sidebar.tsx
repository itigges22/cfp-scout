import { Link } from "@tanstack/react-router";
import {
  ClipboardList,
  CalendarClock,
  GitFork,
  LayoutDashboard,
  Megaphone,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

type NavEntry = {
  to: string;
  label: string;
  Icon: LucideIcon;
};

const SECTIONS: { title: string; entries: NavEntry[] }[] = [
  // One Discover hub: dashboard + the conferences table (which now
  // includes the "Discover more" trigger + approve actions). No
  // standalone /discover entry, no orphan /diagnostics.
  {
    title: "Discover",
    entries: [
      { to: "/dashboard", label: "Dashboard", Icon: LayoutDashboard },
      { to: "/conferences", label: "Conferences", Icon: CalendarClock },
      { to: "/graph", label: "Graph", Icon: GitFork },
    ],
  },
  // Everything the operator manually feeds Scout: who you have on the
  // bench (SMEs), who you're trying to reach (Audiences), how you talk
  // about the products (Messaging), and where you've been already
  // (Past conferences). Section labelled "Info" — these aren't team
  // members, they're the team's reference data.
  {
    title: "Info",
    entries: [
      { to: "/smes", label: "SMEs", Icon: Users },
      { to: "/audiences", label: "Audiences", Icon: ClipboardList },
      { to: "/messaging", label: "Messaging", Icon: Megaphone },
      { to: "/past-conferences", label: "Past events", Icon: CalendarClock },
    ],
  },
  // Settings is the catch-all — Diagnostics + Agent live as sub-links
  // here, not as their own sidebar entries.
  {
    title: "",
    entries: [
      { to: "/settings", label: "Settings", Icon: Settings },
    ],
  },
];

export function Sidebar() {
  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-border bg-surface px-3 py-4">
      {/* Logo / wordmark */}
      <Link
        to="/dashboard"
        className="mb-6 flex items-center gap-2 px-3 text-lg font-semibold tracking-tight"
      >
        <span className="text-accent">●</span>
        <span>Scout</span>
      </Link>

      <nav className="flex flex-1 flex-col gap-6 overflow-y-auto">
        {SECTIONS.map((section, idx) => (
          <div key={section.title || `__unlabeled-${idx}`} className="flex flex-col gap-1">
            {section.title ? (
              <h2 className="px-3 text-xs font-medium uppercase tracking-wider text-fg-subtle">
                {section.title}
              </h2>
            ) : null}
            {section.entries.map(({ to, label, Icon }) => (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium",
                  "text-fg-muted transition-colors",
                  "hover:bg-surface-2 hover:text-fg",
                )}
                activeProps={{
                  className: "bg-surface-2 text-fg",
                }}
              >
                <Icon className="size-4" />
                {label}
              </Link>
            ))}
          </div>
        ))}
      </nav>

      <div className="mt-auto px-3 pt-4 text-xs text-fg-subtle">
        Phase 1 · v0.1.0
      </div>
    </aside>
  );
}
