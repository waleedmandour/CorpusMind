/**
 * cql-ui-regression.test.tsx — v1.2.13-2 hardening round.
 *
 * Covers the review's web items:
 *  - mode toggle renders and switches (shared KWIC table for both modes);
 *  - a 422 CQL syntax error renders the engine's position-annotated detail;
 *  - Cancel aborts an in-flight CQL request (react-query signal -> fetch);
 *  - the elapsed counter ticks while the request is in flight;
 *  - student gating: a 403 from the CQL endpoint hides the CQL toggle,
 *    falls back to Simple, and shows the student notice;
 *  - CQL mode exports server-side (export/concordance/cql, not the
 *    client-side page export);
 *  - the stale-seed bug: two searches with "Random sample" on must each
 *    send the seed that matches the CURRENT click (pre-fix, the second
 *    search reused the first click's seed).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConcordancerView, engineErrorDetail, cqlErrorPosition } from "@/views/ConcordancerView";
import { queryClientDefaults } from "@/lib/queryClient";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";

const makeClient = () => new QueryClient({ defaultOptions: queryClientDefaults });

const KWIC_RESULT = (seed: number | null = 42) => ({
  lines: [
    {
      line_id: "d1:0:1", document_id: "d1", document_filename: "one.txt",
      sentence_idx: 0, token_idx: 1,
      left: "The", node: "quick fox", right: "jumps",
      pos: "ADJ", lemma: "quick",
    },
  ],
  total: 1,
  query: { q: '[pos="ADJ"] "fox"', mode: "cql", window: 5, parsed: '[pos="ADJ"] "fox"', ...(seed != null ? { sample_seed: seed } : {}) },
});

type Mode = "hang" | "ok" | "syntax-422" | "forbidden-403" | "too-expensive-422";
let cqlMode: Mode = "ok";
let cqlCalls = 0;
let lastCqlBody: any = null;
let lastCqlSignal: AbortSignal | null = null;
let pendingCql: { resolve: (r: Response) => void } | null = null;
const exportCalls: string[] = [];

const okJson = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status });

beforeEach(() => {
  cleanup();
  cqlMode = "ok";
  cqlCalls = 0;
  lastCqlBody = null;
  lastCqlSignal = null;
  pendingCql = null;
  exportCalls.length = 0;
  useApp.setState({ activeCorpusId: "c1" });
  useUI.setState({ lang: "en", studentClient: false });
  // jsdom lacks the blob download plumbing — stub it like the Arabic
  // export tests do so downloadBlob completes.
  (globalThis as any).URL.createObjectURL = vi.fn(() => "blob:mock");
  (globalThis as any).URL.revokeObjectURL = vi.fn();
  const origCreate = document.createElement.bind(document);
  vi.spyOn(document, "createElement").mockImplementation((tag: string, opts?: any) => {
    const el = origCreate(tag as any, opts);
    if (tag === "a") (el as any).click = vi.fn();
    return el;
  });
  (globalThis as any).fetch = vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.includes("/export/concordance/cql")) {
      // NOTE: checked BEFORE /concordance — the export URL contains it.
      exportCalls.push(u);
      return Promise.resolve(new Response("Line ID,Node\nd1:0:1,quick fox\n", { status: 200 }));
    }
    if (u.includes("/concordance/cql")) {
      cqlCalls++;
      lastCqlBody = JSON.parse(String(init?.body ?? "{}"));
      lastCqlSignal = init?.signal ?? null;
      if (cqlMode === "syntax-422") {
        return Promise.resolve(okJson({ detail: "Invalid CQL query: position 9: expected a token" }, 422));
      }
      if (cqlMode === "too-expensive-422") {
        return Promise.resolve(okJson({ detail: "CQL query too expensive: query exceeded the matcher work budget (1,500,000 steps). Narrow it." }, 422));
      }
      if (cqlMode === "forbidden-403") {
        return Promise.resolve(okJson({ detail: "Forbidden: this action is not available in Student Mode." }, 403));
      }
      if (cqlMode === "hang") {
        return new Promise<Response>((resolve, reject) => {
          pendingCql = { resolve };
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      }
      return Promise.resolve(okJson(KWIC_RESULT(lastCqlBody?.sample_seed ?? null)));
    }
    if (u.includes("/concordance")) {
      // simple-mode concordance — same response shape, mode "simple"
      lastCqlBody = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve(
        okJson({
          ...KWIC_RESULT(lastCqlBody?.sample_seed ?? null),
          query: { q: "the", level: "word", mode: "simple" },
        }),
      );
    }
    if (u.includes("/corpora/c1")) return Promise.resolve(okJson({ id: "c1", name: "C", language: "en" }));
    return Promise.resolve(okJson({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
  if (pendingCql) {
    pendingCql.resolve(okJson(KWIC_RESULT()));
    pendingCql = null;
  }
});

const sleep = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

const mount = async () => {
  render(
    <QueryClientProvider client={makeClient()}>
      <ConcordancerView />
    </QueryClientProvider>,
  );
  await sleep(120);
};

const searchBtn = () =>
  [...document.querySelectorAll("button")].find((b) => b.textContent === "Search") as HTMLButtonElement;
// the CQL run button shows "Run CQL" when idle and the localized
// "Analyzing… Ns" counter while in flight
const runCqlBtn = () =>
  [...document.querySelectorAll("button")].find((b) =>
    /^(Run CQL|Analyzing… \d+s)$/.test(b.textContent ?? ""),
  ) as HTMLButtonElement | undefined;
const cancelBtn = () =>
  [...document.querySelectorAll("button")].find((b) => b.textContent?.includes("Cancel")) as HTMLButtonElement | undefined;
const modeBtns = () => [...document.querySelectorAll(".mode-toggle-btn")] as HTMLButtonElement[];
const searchInput = () => document.querySelector<HTMLInputElement>(".search-input")!;

describe("CQL mode toggle + shared KWIC table", () => {
  it("starts in Simple mode and switches to CQL (Run CQL button appears)", async () => {
    await mount();
    expect(searchBtn()).toBeTruthy();
    expect(runCqlBtn()).toBeUndefined();
    fireEvent.click(modeBtns()[1]); // CQL
    await sleep(50);
    expect(runCqlBtn()).toBeTruthy();
  });

  it("renders the shared KWIC table for a CQL result", async () => {
    await mount();
    fireEvent.click(modeBtns()[1]);
    fireEvent.change(searchInput(), { target: { value: '[pos="ADJ"] "fox"' } });
    fireEvent.click(runCqlBtn()!);
    await sleep(300);
    const table = document.querySelector("table.kwic-table");
    expect(table).not.toBeNull();
    expect(document.querySelector(".kwic-table .node")?.textContent).toBe("quick fox");
    expect(cqlCalls).toBe(1);
  });
});

describe("CQL error rendering", () => {
  it("422 syntax error shows the position-annotated detail + caret", async () => {
    cqlMode = "syntax-422";
    await mount();
    fireEvent.click(modeBtns()[1]);
    fireEvent.change(searchInput(), { target: { value: '[lemma="x"' } });
    fireEvent.click(runCqlBtn()!);
    await sleep(300);
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("position 9");
    // the caret line points at column 9
    const caret = document.querySelector('[data-testid="cql-error-caret"]');
    expect(caret).not.toBeNull();
    expect(caret?.textContent).toContain("^");
  });

  it("budget overrun 422 renders the actionable message", async () => {
    cqlMode = "too-expensive-422";
    await mount();
    fireEvent.click(modeBtns()[1]);
    fireEvent.change(searchInput(), { target: { value: '"the" []* "of"' } });
    fireEvent.click(runCqlBtn()!);
    await sleep(300);
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("work budget");
  });
});

describe("Cancel + elapsed counter (CQL)", () => {
  it("Run CQL disables while in flight, shows the elapsed counter and Cancel; cancel aborts", async () => {
    cqlMode = "hang";
    await mount();
    fireEvent.click(modeBtns()[1]);
    fireEvent.change(searchInput(), { target: { value: '"the" []* "of"' } });
    fireEvent.click(runCqlBtn()!);
    await sleep(2300);
    expect(cqlCalls).toBe(1);
    expect(runCqlBtn()!.disabled).toBe(true);
    // elapsed counter ticks (>= 1s) while the request hangs
    expect(runCqlBtn()!.textContent || "").toMatch(/^Analyzing… \d+s$/);
    const cancel = cancelBtn();
    expect(cancel).toBeTruthy();
    fireEvent.click(cancel!);
    await sleep(300);
    // the fetch was aborted through react-query's signal
    expect(lastCqlSignal?.aborted).toBe(true);
    expect(cancelBtn()).toBeUndefined();
    expect(runCqlBtn()!.disabled).toBe(false);
  });
});

describe("Student gating", () => {
  it("403 from the CQL endpoint hides the toggle, falls back to Simple, shows the notice", async () => {
    useUI.setState({ studentClient: true });
    cqlMode = "forbidden-403";
    await mount();
    fireEvent.click(modeBtns()[1]);
    fireEvent.change(searchInput(), { target: { value: '"anything"' } });
    fireEvent.click(runCqlBtn()!);
    await sleep(300);
    // toggle is gone; the student notice is shown
    expect(document.querySelector(".mode-toggle")).toBeNull();
    expect(document.body.textContent).toContain("not available in Student Mode");
    // and a Simple search still works (server export path)
    fireEvent.change(searchInput(), { target: { value: "fox" } });
    fireEvent.click(searchBtn());
    await sleep(300);
    expect(document.querySelector("table.kwic-table")).not.toBeNull();
  });
});

describe("Export (server-side CQL)", () => {
  it("CQL mode calls export/concordance/cql (server re-runs the query)", async () => {
    await mount();
    fireEvent.click(modeBtns()[1]);
    fireEvent.change(searchInput(), { target: { value: '"fox"' } });
    fireEvent.click(runCqlBtn()!);
    await sleep(300);
    const exportBtn = [...document.querySelectorAll(".export-trigger")][0] as HTMLButtonElement;
    fireEvent.click(exportBtn);
    await sleep(100);
    const item = [...document.querySelectorAll(".export-menu-item")][0] as HTMLButtonElement;
    fireEvent.click(item); // xlsx
    await sleep(300);
    expect(exportCalls.some((u) => u.includes("/export/concordance/cql"))).toBe(true);
    expect(document.body.textContent).toMatch(/Saved to|Exporting/);
  });
});

describe("Stale-seed bug (P1-9)", () => {
  it("two consecutive sampled searches send DIFFERENT, current seeds", async () => {
    await mount();
    // Simple mode with Random sample checked
    const sample = [...document.querySelectorAll("input[type=checkbox]")].find(
      (el) => (el as HTMLInputElement).closest("label")?.textContent?.includes("Random sample"),
    ) as HTMLInputElement;
    fireEvent.click(sample);
    fireEvent.change(searchInput(), { target: { value: "the" } });
    fireEvent.click(searchBtn());
    await sleep(300);
    const seed1 = lastCqlBody?.sample_seed;
    expect(seed1).toBeTypeOf("number");
    fireEvent.click(searchBtn());
    await sleep(300);
    const seed2 = lastCqlBody?.sample_seed;
    expect(seed2).toBeTypeOf("number");
    // pre-fix: the second click re-sent seed1 (stale state read) — or null
    expect(seed2).not.toBe(seed1);
  });
});

describe("error detail helpers", () => {
  it("engineErrorDetail unwraps FastAPI 422 detail", () => {
    const e = new Error('HTTP 422: {"detail":"Invalid CQL query: position 9: boom"}');
    expect(engineErrorDetail(e)).toContain("position 9");
  });
  it("cqlErrorPosition extracts the caret column", () => {
    expect(cqlErrorPosition("Invalid CQL query: position 12: expected ']'")).toBe(12);
    expect(cqlErrorPosition("no position here")).toBeNull();
  });
});
