import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from "@tanstack/react-query";

import App from "@/App";
import "@/styles/global.css";
import { useTroubleshoot } from "@/store/troubleshooting";
import { api } from "@/lib/api";

// ----------------------------------------------------------------------- //
// React Query setup with global error handler that feeds Smart Troubleshooting.
// ----------------------------------------------------------------------- //

/** Extract the URL/endpoint from a Query function's stringified form or a fetch error. */
function extractEndpointFromError(_error: unknown): string | null {
  // jsonFetch throws `Error("HTTP 404: <body>")` — the URL isn't in the
  // message, but we can extract it from the query key if available via
  // the QueryCache. For now, we return null and rely on the context arg
  // passed by the global onError callbacks below.
  return null;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
  queryCache: new QueryCache({
    onError: (error, query) => {
      // Don't capture health-check failures here — the dedicated health
      // poller in the troubleshooting store handles those, and we don't
      // want to double-report them.
      if (query.queryKey[0] === "health") return;

      const message = error instanceof Error ? error.message : String(error);
      const endpoint = typeof query.queryKey[1] === "string"
        ? (query.queryKey[1] as string)
        : extractEndpointFromError(error);

      useTroubleshoot.getState().captureError({
        message,
        endpoint,
        context: `Background query: ${String(query.queryKey[0])}`,
      });
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      const message = error instanceof Error ? error.message : String(error);
      useTroubleshoot.getState().captureError({
        message,
        context: `Action: ${mutation.options.mutationKey?.[0] ?? "unknown"}`,
      });
    },
  }),
});

// ----------------------------------------------------------------------- //
// Initialize Smart Troubleshooting: check Gemini availability + start polling.
// ----------------------------------------------------------------------- //

async function initTroubleshooting() {
  // Check if Gemini interpretation is available (key configured in engine)
  try {
    const status = await api.troubleshootStatus();
    useTroubleshoot.getState().setGeminiAvailable(status.available);
  } catch {
    // Engine not reachable yet — that's fine, the health poller will catch it
  }
  // Start the background health poller
  useTroubleshoot.getState().startHealthPolling();
}

void initTroubleshooting();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
