import { Outlet, createRootRoute } from "@tanstack/react-router";
import { createContext, useState } from "react";

import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";

export const SidebarContext = createContext<{
  open: boolean;
  toggle: () => void;
}>({ open: false, toggle: () => {} });

// Root route. Wraps every page in the AppShell (sidebar + topbar + main).
//
// Route components below this point only render the "main" content area —
// Scout never has a route without the shell.

export const Route = createRootRoute({
  component: RootComponent,
});

function RootComponent() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <SidebarContext.Provider value={{ open: sidebarOpen, toggle: () => setSidebarOpen((o) => !o) }}>
      <div className="flex h-full">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="flex-1 overflow-x-hidden overflow-y-auto bg-canvas px-4 py-6 lg:px-8">
            <Outlet />
          </main>
        </div>
      </div>
    </SidebarContext.Provider>
  );
}
