/**
 * arabic-ui-regression.test.tsx — v1.2.12-rc7.
 *
 * Field report: Arabic Tools stuck on a DISABLED "Analyzing… 0s" + Cancel
 * from the moment the view opened (no analysis could ever be started).
 *
 * Root cause (TanStack Query v5 semantics): a query whose options contain
 * `enabled:` reports `isPending === true` from the first render (status
 * "pending", fetchStatus "idle") — before it has ever run. ArabicView used
 * `result.isPending` as the in-flight flag, so the Run button was disabled
 * and the spinner shown while the query was in fact merely idle. tsc cannot
 * see this bug class; scripts/check_query_pending.mjs guards the sources and
 * THIS file proves the actual UI behaviour.
 *
 * The QueryClient defaults come from the same shared module the shipped app
 * uses (web/src/lib/queryClient.ts), so the tests cannot drift from runtime
 * behaviour (e.g. the app-wide `retry: 1` vs the Arabic query's own
 * `retry: false`).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArabicView } from "@/views/ArabicView";
import { queryClientDefaults } from "@/lib/queryClient";

// EXACT defaults used by the shipped app (web/src/main.tsx).
const makeClient = () => new QueryClient({ defaultOptions: queryClientDefaults });

let analyzeCalls = 0;
let pending: { resolve: (r: Response) => void } | null = null;
let mode: "hang" | "error-504" | "ok" = "hang";
const okJson = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });

beforeEach(() => {
  cleanup();
  analyzeCalls = 0; pending = null; mode = "hang";
  (globalThis as any).fetch = vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.includes("/arabic/backends")) return Promise.resolve(okJson({ backends: [{ name: "camel", available: true, model: "calima-msa-r13", version: "1" }] }));
    if (u.includes("/arabic/data/install/status")) return Promise.resolve(okJson({ camel_tools: { morphology_dbs: { msa: true, egy: false, glf: false, lev: false } } }));
    if (u.includes("/arabic/analyze")) {
      analyzeCalls++;
      if (mode === "error-504") return Promise.resolve(okJson({ detail: "timeout" }, 504));
      if (mode === "ok") return Promise.resolve(okJson({ backend: "camel", model: "calima-msa-r13", tokens: [], n_tokens: 0, elapsed_ms: 1 }));
      return new Promise<Response>((resolve, reject) => {
        pending = { resolve };
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    }
    return Promise.resolve(okJson({}));
  });
});

afterEach(() => {
  cleanup();
  // Unblock any request still hanging from a test that never cancelled it,
  // so no withDeadline timer (150 s) survives into the worker teardown.
  if (pending) { pending.resolve(okJson({ backend: "camel", model: "calima-msa-r13", tokens: [], n_tokens: 0, elapsed_ms: 1 })); pending = null; }
});

const sleep = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
const run = () => document.querySelector(".run-btn:not(.run-btn-cancel)") as HTMLButtonElement;
const cancel = () => document.querySelector(".run-btn-cancel") as HTMLButtonElement | null;
const mount = async () => {
  render(<QueryClientProvider client={makeClient()}><ArabicView /></QueryClientProvider>);
  await sleep(300);
};

describe("Arabic Tools run button (field report: stuck on 'Analyzing… 0s')", () => {
  it("(a) idle view offers an ENABLED 'Run analysis' and no Cancel", async () => {
    await mount();
    expect(run().textContent).toBe("Run analysis");
    expect(run().disabled).toBe(false);
    expect(cancel()).toBeNull();
    expect(analyzeCalls).toBe(0);
  });

  it("(b) click -> exactly one request, button disabled, counter ticks, Cancel appears", async () => {
    await mount();
    fireEvent.click(run());
    await sleep(2300);
    expect(analyzeCalls).toBe(1);
    expect(run().disabled).toBe(true);
    expect(run().textContent).toMatch(/Analyzing… [12]s/);
    expect(cancel()).not.toBeNull();
  });

  it("(c) Cancel aborts the request and returns to a clickable 'Run analysis'", async () => {
    await mount();
    fireEvent.click(run());
    await sleep(500);
    fireEvent.click(cancel()!);
    await sleep(300);
    expect(run().textContent).toBe("Run analysis");
    expect(run().disabled).toBe(false);
    expect(cancel()).toBeNull();
  });

  it("(d) success clears the spinner and shows the result", async () => {
    mode = "ok";
    await mount();
    fireEvent.click(run());
    await sleep(500);
    expect(run().textContent).toBe("Run analysis");
    expect(run().disabled).toBe(false);
    expect(document.querySelector(".result-block")).not.toBeNull();
  });

  it("(e) after a 504, clicking Run with identical input fires a NEW request", async () => {
    mode = "error-504";
    await mount();
    fireEvent.click(run());
    await sleep(500);
    expect(analyzeCalls).toBe(1);
    expect(run().disabled).toBe(false);            // spinner resolved, button usable
    fireEvent.click(run());                        // same text/tool/dialect/tagset
    await sleep(500);
    expect(analyzeCalls).toBe(2);                  // pre-fix: stayed at 1 (no-op click)
  });
});
