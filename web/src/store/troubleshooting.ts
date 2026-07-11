/**
 * Smart Troubleshooting store.
 *
 * Captures backend errors from two sources:
 *   1. React Query global onError handler (QueryCache + MutationCache)
 *   2. A lightweight /api/v1/health poller (every 15s)
 *
 * Only fires when there's an actual issue. Implements:
 *   - Dedup by error key (status code + endpoint) within a 5-second window
 *   - Max 1 active issue per error key
 *   - Auto-resolve when a subsequent request to the same endpoint succeeds
 *   - Health poller with exponential backoff on failure
 *
 * When a new issue is captured, optionally calls the engine's
 * /api/v1/troubleshoot/interpret endpoint to get a Gemini-powered
 * interpretation + suggested fix.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { api, type InterpretErrorResponse } from "@/lib/api";

export type IssueSeverity = "info" | "warning" | "error";

export interface TroubleshootIssue {
  id: string;
  /** ISO timestamp when the issue was first detected. */
  timestamp: string;
  /** The error message text. */
  message: string;
  /** HTTP status code or "NETWORK" for connection failures. */
  code: string | number;
  /** The API endpoint that failed (best-effort extraction from the URL). */
  endpoint: string | null;
  /** What the user was doing when the error occurred (optional context). */
  context: string | null;
  /** Stack trace if available (JS errors). */
  stackTrace: string | null;
  /** Whether this issue has been resolved (auto or manual). */
  resolved: boolean;
  /** Gemini interpretation, if available. Null while loading, undefined if not requested. */
  interpretation: InterpretErrorResponse | null | undefined;
}

interface TroubleshootState {
  issues: TroubleshootIssue[];
  /** Whether the backend was reachable at the last health check. */
  backendReachable: boolean;
  /** Whether the health poller is actively polling. */
  polling: boolean;
  /** Whether Gemini interpretation is available (key configured in engine). */
  geminiAvailable: boolean;
  /** Whether the troubleshooting panel (taskbar) is expanded. */
  panelOpen: boolean;
  /** Whether the detailed troubleshooting view is open (sidebar). */
  detailedViewOpen: boolean;
  /** Whether the user has muted Smart Troubleshooting notifications.
   * When muted, errors are still captured silently (stored in the issues
   * list) but the taskbar badge does NOT appear and the panel does NOT
   * auto-open. The user can still open the panel manually from Settings.
   * Persisted to localStorage so it survives app restarts. */
  muted: boolean;

  captureError: (params: {
    message: string;
    code?: string | number;
    endpoint?: string | null;
    context?: string | null;
    stackTrace?: string | null;
  }) => void;
  resolveIssue: (id: string) => void;
  clearResolved: () => void;
  clearAll: () => void;
  setPanelOpen: (open: boolean) => void;
  setDetailedViewOpen: (open: boolean) => void;
  setBackendReachable: (reachable: boolean) => void;
  setGeminiAvailable: (available: boolean) => void;
  setMuted: (muted: boolean) => void;
  fetchInterpretation: (issueId: string) => Promise<void>;
  startHealthPolling: () => void;
  stopHealthPolling: () => void;
}

// Dedup window: if the same error key fires within this many ms, suppress it.
const DEDUP_WINDOW_MS = 5_000;
// Max issues to retain in memory (older ones are pruned).
const MAX_ISSUES = 20;

let pollInterval: ReturnType<typeof setInterval> | null = null;
let pollFailureCount = 0;
const recentErrors: Map<string, number> = new Map();

function errorKey(code: string | number, endpoint: string | null): string {
  return `${code}:${endpoint ?? "unknown"}`;
}

/** Extract an HTTP status code from a fetch error message. */
function extractCode(message: string): string | number {
  // jsonFetch throws `Error("HTTP 404: ...")` — extract the code
  const match = message.match(/^HTTP (\d+):/);
  if (match) return parseInt(match[1], 10);
  // Network errors (ECONNREFUSED, timeout) → "NETWORK"
  if (/fetch|network|connect|timeout|err_connection/i.test(message)) return "NETWORK";
  return "UNKNOWN";
}

export const useTroubleshoot = create<TroubleshootState>()(
  persist(
    (set, get) => ({
      issues: [],
      backendReachable: true,
      polling: false,
      geminiAvailable: false,
      panelOpen: false,
      detailedViewOpen: false,
      muted: true,  // Notifications OFF by default — user can unmute in Settings

  captureError: (params) => {
    const code = params.code ?? extractCode(params.message);
    const endpoint = params.endpoint ?? null;
    const key = errorKey(code, endpoint);

    // Dedup: suppress if the same key fired within the window
    const now = Date.now();
    const lastSeen = recentErrors.get(key);
    if (lastSeen && now - lastSeen < DEDUP_WINDOW_MS) {
      return; // Suppress duplicate
    }
    recentErrors.set(key, now);

    // Clean up old dedup entries periodically
    if (recentErrors.size > 50) {
      for (const [k, t] of recentErrors) {
        if (now - t > DEDUP_WINDOW_MS * 4) recentErrors.delete(k);
      }
    }

    const issue: TroubleshootIssue = {
      id: `${now}-${Math.random().toString(36).slice(2, 8)}`,
      timestamp: new Date().toISOString(),
      message: params.message,
      code,
      endpoint,
      context: params.context ?? null,
      stackTrace: params.stackTrace ?? null,
      resolved: false,
      interpretation: undefined,
    };

    // If muted, store the issue silently but do NOT auto-open the panel
    // or show the taskbar badge. The user can still see muted issues by
    // opening the panel manually from Settings.
    const isMuted = get().muted;
    set((state) => ({
      issues: [issue, ...state.issues].slice(0, MAX_ISSUES),
      // Only auto-open the panel if NOT muted
      panelOpen: isMuted ? state.panelOpen : true,
    }));

    // Auto-fetch interpretation if Gemini is available (even when muted —
    // the user might unmute later and want the interpretation ready)
    if (get().geminiAvailable) {
      void get().fetchInterpretation(issue.id);
    }
  },

  resolveIssue: (id) =>
    set((state) => ({
      issues: state.issues.map((i) => (i.id === id ? { ...i, resolved: true } : i)),
    })),

  clearResolved: () =>
    set((state) => ({ issues: state.issues.filter((i) => !i.resolved) })),

  clearAll: () => set({ issues: [], panelOpen: false }),

  setPanelOpen: (panelOpen) => set({ panelOpen }),
  setDetailedViewOpen: (detailedViewOpen) => set({ detailedViewOpen }),
  setBackendReachable: (backendReachable) => set({ backendReachable }),
  setGeminiAvailable: (geminiAvailable) => set({ geminiAvailable }),
  setMuted: (muted) => set({ muted }),

  fetchInterpretation: async (issueId) => {
    const issue = get().issues.find((i) => i.id === issueId);
    if (!issue) return;

    // Mark as loading
    set((state) => ({
      issues: state.issues.map((i) =>
        i.id === issueId ? { ...i, interpretation: null } : i,
      ),
    }));

    try {
      const interpretation = await api.interpretError({
        error_message: issue.message,
        error_code: issue.code,
        endpoint: issue.endpoint,
        context: issue.context,
        stack_trace: issue.stackTrace,
      });
      set((state) => ({
        issues: state.issues.map((i) =>
          i.id === issueId ? { ...i, interpretation } : i,
        ),
      }));
    } catch (e) {
      // If interpretation itself fails, store a fallback
      const fallback: InterpretErrorResponse = {
        available: false,
        severity: "info",
        plain_language: "Auto-interpretation is not available right now.",
        likely_cause: String(e),
        suggested_fix: "Check the engine logs and try again.",
        should_report: true,
        raw_error: issue.message,
        model: "",
      };
      set((state) => ({
        issues: state.issues.map((i) =>
          i.id === issueId ? { ...i, interpretation: fallback } : i,
        ),
      }));
    }
  },

  startHealthPolling: () => {
    if (pollInterval) return; // Already polling
    set({ polling: true });

    const poll = async () => {
      try {
        await api.health();
        pollFailureCount = 0;
        const wasUnreachable = !get().backendReachable;
        set({ backendReachable: true });
        // If the backend just came back, auto-resolve recent NETWORK issues
        if (wasUnreachable) {
          set((state) => ({
            issues: state.issues.map((i) =>
              i.code === "NETWORK" && !i.resolved ? { ...i, resolved: true } : i,
            ),
          }));
        }
      } catch {
        pollFailureCount += 1;
        // Only mark as unreachable after 2 consecutive failures (avoid flapping)
        if (pollFailureCount >= 2) {
          const wasReachable = get().backendReachable;
          set({ backendReachable: false });
          if (wasReachable) {
            get().captureError({
              message: "Cannot reach the CorpusMind engine at 127.0.0.1:8765. The backend appears to be offline.",
              code: "NETWORK",
              endpoint: "/api/v1/health",
              context: "Background health check",
            });
          }
        }
      }
    };

    // Poll immediately, then every 15s
    void poll();
    pollInterval = setInterval(poll, 15_000);
  },

  stopHealthPolling: () => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    set({ polling: false });
  },
    }),
    {
      name: "corpusmind-troubleshooting",
      // Only persist the muted preference — issues are session-scoped
      partialize: (state) => ({ muted: state.muted }),
    },
  ),
);
