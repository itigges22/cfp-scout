import { QueryClient } from "@tanstack/react-query";

// Project-wide TanStack Query client. Reused via QueryClientProvider in main.tsx.
//
//   * 30s staleTime — most data the team views is freshish but not real-time.
//   * 3 retries with exponential backoff — covers transient blips.
//   * refetchOnWindowFocus: TRUE. This was false with the comment "the user
//     knows when to refresh" — which is exactly the failure it produced:
//     add something, tab away, come back, and the list is silently stale
//     until a hard refresh. Focus-refetch is the safety net that catches
//     any mutation whose cache invalidation missed a page.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 3,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30_000),
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: 0,
    },
  },
});
