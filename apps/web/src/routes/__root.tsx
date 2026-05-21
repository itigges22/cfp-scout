import { Outlet, createRootRoute } from "@tanstack/react-router";

import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";

// Root route. Wraps every page in the AppShell (sidebar + topbar + main).
//
// Route components below this point only render the "main" content area —
// Scout never has a route without the shell.

export const Route = createRootRoute({
  component: RootComponent,
});

function RootComponent() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <TopBar />
        <main className="flex-1 overflow-y-auto bg-canvas px-8 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
