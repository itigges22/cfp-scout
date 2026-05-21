import { createFileRoute, redirect } from "@tanstack/react-router";

// `/` redirects to /dashboard. Dashboard is Scout's home.

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/dashboard" });
  },
});
