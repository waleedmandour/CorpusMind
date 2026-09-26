import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from "@tanstack/react-query";

import App from "@/App";
import "@/styles/global.css";
import { useTroubleshoot } from "@/store/troubleshooting";
import { api, isTauriRuntime, setStudentSession } from "@/lib/api";

// ----------------------------------------------------------------------- //
// v1.2.9 Student Mode bootstrap — MUST run before the first render.
//
// The teacher's QR encodes the classroom server, the student token, and
// the mode flag:  ?mode=student&server=https%3A%2F%2F192.168.1.10%3A8483&token=…
// We commit them to the student session (localStorage) here so that App's
// first render — and every api.ts fetch — already targets the classroom.
// A previous session persists, so a plain reload keeps working.
// ----------------------------------------------------------------------- //
try {
  const params = new URLSearchParams(window.location.search);
  const server = params.get("server");
  const token = params.get("token");
  if (params.get("mode") === "student") {
    if (server) setStudentSession(server, token ?? "");
    else if (token) {
      // Token-only link: keep the previously saved server, refresh the token.
      const saved = localStorage.getItem("corpusmind-student-server");
      if (saved) setStudentSession(saved, token);
    }
  }
  if (params.get("mode") === "teacher") {
    // Explicit escape hatch: leave the classroom client on this device.
    localStorage.removeItem("corpusmind-student-server");
    localStorage.removeItem("corpusmind-student-token");
  }
} catch {
  /* storage unavailable — student connect form still works without persistence */
}

// ----------------------------------------------------------------------- //
// PWA service worker registration.
//
// The service worker is ONLY for the browser PWA (offline support). It must
// NOT run inside the Tauri desktop webview — inside WebView2 (Windows), the
// service worker intercepts every fetch to http://127.0.0.1:8765 and fails
// with net::ERR_FAILED, breaking all engine API calls. This is the root cause
// of the "Detected (API unreachable)" amber state on Windows desktop builds.
//
// v1.2.9 Student Mode: a service worker also requires a secure context.
// Over the classroom's plain-HTTP "Simple" mode the page is NOT secure,
// so registration is skipped (the app still works as a regular page; the
// secure mode's local-CA HTTPS gets full PWA installability).
// ----------------------------------------------------------------------- //
if (!isTauriRuntime() && typeof window !== "undefined" && window.isSecureContext) {
  // vite-plugin-pwa provides the virtual module; the import is tree-shaken
  // out of the Tauri build because isTauriRuntime() is false at runtime, but
  // the module is still bundled (the SW file is generated regardless).
  import("virtual:pwa-register").then(({ registerSW }) => {
    registerSW({ immediate: true });
  }).catch(() => {
    // Non-fatal: the SW is optional (offline PWA support only).
  });
}

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
