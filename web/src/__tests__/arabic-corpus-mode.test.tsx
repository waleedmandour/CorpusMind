/**
 * arabic-corpus-mode.test.tsx — r4.
 *
 * Field request: the Arabic Tools panel only offered a paste-text box; the
 * corpus workflow lived entirely in 'Your Corpus'. r4 adds an input-source
 * toggle: "Enter text" (per-tool endpoints, unchanged) vs "Pre-loaded
 * corpus" — the panel lists the project's ARABIC corpora (language === "ar")
 * and starts the engine's chunked bulk job (POST /arabic/analyze/job with
 * corpus_id), polling status and rendering the aggregated report.
 *
 * Behaviour pinned here:
 *   (a) default is text mode (textarea visible) — zero behaviour change,
 *   (b) corpus mode lists ONLY Arabic-language corpora,
 *   (c) no Arabic corpora -> actionable hint + working "Go to Your Corpus"
 *       navigation (setActiveNav("corpus-target")),
 *   (d) Run -> exactly one POST carrying corpus_id -> progress -> done ->
 *       aggregated report (summary + roots table) rendered,
 *   (e) Cancel -> POST .../job/cancel.
 *
 * Fetch is mocked at the global level, same technique as
 * arabic-ui-regression.test.tsx; QueryClient defaults come from the shared
 * queryClient module so the tests cannot drift from runtime behaviour.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArabicView } from "@/views/ArabicView";
import { queryClientDefaults } from "@/lib/queryClient";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";

const makeClient = () => new QueryClient({ defaultOptions: queryClientDefaults });

const AR_CORPUS = {
  id: "c-ar", project_id: "p1", name: "Arabic news corpus", language: "ar", genre: "news",
  pipeline_recipe: {}, stats: { token_count: 12345 }, created_at: "2026-01-01",
  document_count: 3, image_set_count: 0,
};
const EN_CORPUS = {
  id: "c-en", project_id: "p1", name: "English essays", language: "en", genre: "academic",
  pipeline_recipe: {}, stats: { token_count: 9000 }, created_at: "2026-01-02",
  document_count: 2, image_set_count: 0,
};

let corpora: typeof AR_CORPUS[] = [];
let jobState: "idle" | "running" | "done" | "cancelled" | "error" = "idle";
let startCalls = 0;
let startBody = "";
let cancelCalls = 0;
const okJson = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });

const BULK_RESULT = {
  kind: "arabic_bulk_analysis",
  chunks: 2,
  token_count: 4321,
  unique_tokens: 987,
  broken_plural_count: 12,
  pos_distribution: { noun: 3000, verb: 1000, adj: 321 },
  top_roots: [["ك.ت.ب", 1200], ["د.خ.ل", 300]],
  top_patterns: [["1َ2َ3َل", 900]],
  top_lemmas: [["كِتَاب", 800]],
  top_tokens: [["الكتاب", 500]],
  generated_at: 0,
};

const jobStatus = () => ({
  state: jobState,
  busy: jobState === "running",
  stage: jobState === "running" ? "analyzing" : jobState,
  source: "Arabic news corpus",
  chunks_total: 2, chunks_done: jobState === "done" ? 2 : 1,
  tokens_total: 4321, tokens_done: jobState === "done" ? 4321 : 2000,
  elapsed_s: 3, eta_s: jobState === "running" ? 12 : null,
  error: null,
  result_available: jobState === "done",
});

beforeEach(() => {
  cleanup();
  corpora = [AR_CORPUS, EN_CORPUS];
  jobState = "idle"; startCalls = 0; startBody = ""; cancelCalls = 0;
  useApp.setState({ activeProjectId: "p1", activeCorpusId: null });
  (globalThis as any).fetch = vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();
    if (u.includes("/arabic/backends")) return Promise.resolve(okJson({ backends: [{ name: "camel", available: true, model: "calima-msa-r13" }] }));
    if (u.includes("/arabic/data/install/status")) return Promise.resolve(okJson({ camel_tools: { morphology_dbs: { msa: true, egy: false, glf: false, lev: false } } }));
    if (u.includes("/api/v1/projects/p1/corpora")) return Promise.resolve(okJson(corpora));
    if (u.includes("/arabic/analyze/job/status")) return Promise.resolve(okJson(jobStatus()));
    if (u.includes("/arabic/analyze/job/cancel")) {
      cancelCalls++;
      jobState = "cancelled";
      return Promise.resolve(okJson(jobStatus()));
    }
    if (u.includes("/arabic/analyze/job/result")) return Promise.resolve(okJson(BULK_RESULT));
    if (u.includes("/arabic/analyze/job") && method === "POST") {
      startCalls++;
      startBody = String(init?.body ?? "");
      jobState = "running";
      return Promise.resolve(okJson(jobStatus()));
    }
    return Promise.resolve(okJson({}));
  });
});

afterEach(() => {
  cleanup();
});

const sleep = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)) });
// Deterministic wait for the 1s status-poll cadence: short act-flushed sleeps
// let the refetchInterval timers and their promise chains settle between
// checks (one long await starves them). Per-test timeout must exceed the
// total window — the vitest default is 5s.
const waitFor = async (fn: () => boolean, timeout = 8000, what = "condition") => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (fn()) return;
    await sleep(200);
  }
  throw new Error(`waitFor timed out: ${what}`);
};
const mount = async () => {
  render(<QueryClientProvider client={makeClient()}><ArabicView /></QueryClientProvider>);
  await sleep(300);
};
const corpusTab = () => document.querySelectorAll(".ar-source-btn")[1] as HTMLButtonElement;
const runBtn = () => document.querySelector(".ar-bulk-controls .run-btn") as HTMLButtonElement | null;

describe("Arabic Tools corpus mode (r4: reads corpora uploaded in 'Your Corpus')", () => {
  it("(a) default is text mode — textarea visible, no corpus controls", async () => {
    await mount();
    expect(document.querySelector(".arabic-textarea")).not.toBeNull();
    expect(document.querySelector(".ar-corpus-panel")).toBeNull();
    expect(runBtn()).toBeNull();
  });

  it("(b) corpus mode lists ONLY Arabic-language corpora", async () => {
    await mount();
    fireEvent.click(corpusTab());
    await sleep(300);
    const select = document.querySelector(".ar-corpus-picker select") as HTMLSelectElement;
    expect(select).not.toBeNull();
    const names = Array.from(select.options).map((o) => o.textContent ?? "");
    expect(names).toHaveLength(1);
    expect(names[0]).toContain("Arabic news corpus");
    expect(names[0]).not.toContain("English essays");
  });

  it("(c) no Arabic corpora -> hint + 'Go to Your Corpus' navigates", async () => {
    corpora = [EN_CORPUS];
    await mount();
    fireEvent.click(corpusTab());
    await sleep(300);
    expect(document.querySelector(".ar-corpus-picker")).toBeNull();
    const empty = document.querySelector(".ar-corpus-empty");
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain("No Arabic corpora found");
    const go = empty!.querySelector("button") as HTMLButtonElement;
    fireEvent.click(go);
    expect(useUI.getState().activeNav).toBe("corpus-target");
  });

  it("(d) Run -> one corpus_id POST, progress, then the aggregated report", async () => {
    await mount();
    fireEvent.click(corpusTab());
    await sleep(300);
    fireEvent.click(runBtn()!);
    await sleep(400);
    expect(startCalls).toBe(1);
    expect(JSON.parse(startBody)).toEqual({ corpus_id: "c-ar" });
    // Job reported busy: Run button flips to the analyzing state.
    expect(runBtn()!.disabled).toBe(true);
    expect(runBtn()!.textContent).toMatch(/Analyzing corpus… \d+s/);
    expect(document.querySelector(".ar-bulk-progress")).not.toBeNull();
    // The 1s status poll observes the "done" transition, then the result
    // query fetches the aggregated report (both real async cadences).
    jobState = "done";
    await waitFor(
      () => document.querySelector(".ar-corpus-panel")!.textContent!.includes("Full-corpus analysis complete"),
      8000,
      "bulk result panel",
    );
    expect(document.querySelector(".ar-corpus-panel")!.textContent).toContain("ك.ت.ب");
    expect(startCalls).toBe(1);
  }, 15000);

  it("(e) Cancel POSTs to the job cancel endpoint", async () => {
    await mount();
    fireEvent.click(corpusTab());
    await sleep(300);
    fireEvent.click(runBtn()!);
    await sleep(400);
    fireEvent.click(document.querySelector(".ar-bulk-controls .run-btn-cancel") as HTMLButtonElement);
    // act flush: the mutation's fetch lands a microtask after the click.
    await sleep(200);
    expect(cancelCalls).toBe(1);
    // The next status poll observes "cancelled" and the UI resets.
    await waitFor(
      () => document.querySelector(".ar-corpus-panel")!.textContent!.includes("Analysis cancelled"),
      8000,
      "cancelled status",
    );
  }, 15000);
});
