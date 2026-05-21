import { QueryClient } from "@tanstack/react-query";

// Project-wide TanStack Query client. Reused via QueryClientProvider in main.tsx.
//
// Defaults tuned for an internal tool:
//   * 30s staleTime — most data the team views is freshish but not real-time.
//     CFP-digest + diagnostics override per-query when they need tighter freshness.
//   * 3 retries on failure with exponential backoff — covers transient network
//     blips against LLM API / Postgres without hammering on real outages.
//   * `refetchOnWindowFocus: false` — internal tool, the user knows when to refresh.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 3,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30_000),
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
});
