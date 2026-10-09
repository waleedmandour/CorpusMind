/**
 * Shared TanStack Query client defaults — v1.2.12 (rc7).
 *
 * Single source of truth for the app's QueryClient default options, used by
 * BOTH the shipped app (main.tsx) and the UI regression tests
 * (src/__tests__/arabic-ui-regression.test.tsx) so the two cannot drift.
 * The Arabic Tools tests are only meaningful when they run against the exact
 * retry/staleTime behaviour users get at runtime (e.g. the "retry: 1" default
 * vs the Arabic analysis query's own `retry: false` override).
 *
 * Note on v5 semantics (see also scripts/check_query_pending.mjs): these
 * defaults intentionally do NOT touch `isPending` semantics — for any query
 * whose options contain `enabled:`, `isPending` is true from the first render
 * (status "pending", fetchStatus "idle"). In-flight flags must use
 * `isFetching` / `isLoading`.
 */
export const queryClientDefaults = {
  queries: {
    retry: 1,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  },
};
