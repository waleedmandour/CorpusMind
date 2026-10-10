/**
 * result-export.test.tsx — v1.2.13-1.
 *
 * Covers the two user-facing features shipped with the CQL pre-release:
 *
 *  1. Arabic Tools Export (field request): every tool result in the Arabic
 *     Tools window now exports through the same xlsx/csv/tsv/txt/json
 *     dropdown as the analysis panels. The per-tool table shaping lives in
 *     lib/resultExport (arabicResultToTable) — unit-tested here against a
 *     realistic payload per tool kind, including the Arabic columns and the
 *     "-" placeholder for missing morphology components. A render test
 *     proves the Export dropdown actually appears once a result is on
 *     screen and that choosing CSV produces a download attempt with the
 *     right filename.
 *
 *  2. CQL query mode (Concordancer): the Simple|CQL toggle drives the new
 *     POST /concordance/cql call; a CQL result renders through the existing
 *     KWIC table; an invalid pattern surfaces the engine's position-
 *     annotated 422 detail instead of a raw HTTP/JSON dump.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  arabicResultToTable,
  concordanceLinesToTable,
  serializeTable,
  flattenDataToTable,
} from "@/lib/resultExport";
import { ArabicView } from "@/views/ArabicView";
import { ConcordancerView } from "@/views/ConcordancerView";
import { useApp } from "@/store/app";
import { queryClientDefaults } from "@/lib/queryClient";

const makeClient = () => new QueryClient({ defaultOptions: queryClientDefaults });

const okJson = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

// --------------------------------------------------------------------- //
// 1a. arabicResultToTable — one curated table per tool
// --------------------------------------------------------------------- //

describe("arabicResultToTable", () => {
  it("morphology: on-screen columns, Arabic headers, '-' for missing root/pattern", () => {
    const t = arabicResultToTable({
      kind: "morphology",
      data: {
        backend: "camel",
        tokens: [
          { text: "الطلاب", root: "طلب", pattern: "فاعل", lemma: "طالب", pos: "noun", stem: "طلاب", buckwalter: "AlTAlAb" },
          { text: "في", root: null, pattern: "", lemma: "في", pos: "prep", stem: "في", buckwalter: "fy" },
        ],
      },
    });
    expect(t.headers).toEqual(["Token", "Root (الجذر)", "Pattern (الوزن)", "Lemma", "POS", "Stem", "Buckwalter"]);
    expect(t.rows).toHaveLength(2);
    expect(t.rows[0]).toEqual(["الطلاب", "طلب", "فاعل", "طالب", "noun", "طلاب", "AlTAlAb"]);
    expect(t.rows[1]).toEqual(["في", "-", "-", "في", "prep", "في", "fy"]);
  });

  it("roots: Token/Root/Pattern/Lemma/POS", () => {
    const t = arabicResultToTable({
      kind: "roots",
      data: { roots: [{ token: "كتاب", root: "كتب", pattern: "فعال", lemma: "كتاب", pos: "noun" }] },
    });
    expect(t.headers).toEqual(["Token", "Root (الجذر)", "Pattern (الوزن)", "Lemma", "POS"]);
    expect(t.rows).toEqual([["كتاب", "كتب", "فعال", "كتاب", "noun"]]);
  });

  it("clitics: Surface/Stem/POS", () => {
    const t = arabicResultToTable({
      kind: "clitics",
      data: { segments: [{ surface: "وبالكتاب", stem: "كتاب", pos: "noun" }] },
    });
    expect(t.headers).toEqual(["Surface", "Stem", "POS"]);
    expect(t.rows).toEqual([["وبالكتاب", "كتاب", "noun"]]);
  });

  it.each(["buckwalter", "dediac", "normalize"] as const)("text tools (%s): Original/Result pair", (kind) => {
    const field = kind === "buckwalter" ? "buckwalter" : kind === "dediac" ? "dediacritized" : "normalized";
    const t = arabicResultToTable({ kind, data: { original: "الْكِتَاب", [field]: "الكتاب" } });
    expect(t.rows).toEqual([["الْكِتَاب", "الكتاب"]]);
  });

  it("dialect/register: sorted probability table (descending)", () => {
    const d = arabicResultToTable({
      kind: "dialect",
      data: { dialect_distribution: { egy: 0.72, msa: 0.2, glf: 0.08, lev: 0.0 } },
    });
    expect(d.headers).toEqual(["Dialect", "Probability"]);
    expect(d.rows).toEqual([
      ["egy", "72.0%"],
      ["msa", "20.0%"],
      ["glf", "8.0%"],
      ["lev", "0.0%"],
    ]);
    const r = arabicResultToTable({
      kind: "register",
      data: { register_distribution: { formal: 0.9, informal: 0.1 } },
    });
    expect(r.headers).toEqual(["Register", "Probability"]);
    expect(r.rows[0]).toEqual(["formal", "90.0%"]);
  });

  it("translate: one row per equivalent", () => {
    const t = arabicResultToTable({
      kind: "translate",
      data: { word: "كتاب", direction: "ar-en", source: "starter-dictionary", equivalents: ["book", "volume"] },
    });
    expect(t.headers).toEqual(["Word", "Direction", "Equivalent"]);
    expect(t.rows).toEqual([
      ["كتاب", "ar-en", "book"],
      ["كتاب", "ar-en", "volume"],
    ]);
  });

  it("unknown kind: falls back to the generic flattener instead of crashing", () => {
    const t = arabicResultToTable({ kind: "future-tool", data: { alpha: 1, beta: "x" } } as any);
    expect(t.headers).toEqual(["key", "value"]);
    expect(t.rows).toContainEqual(["alpha", "1"]);
  });
});

// --------------------------------------------------------------------- //
// 1b. table serialization (shared with every export path)
// --------------------------------------------------------------------- //

describe("serializeTable / flattenDataToTable / concordanceLinesToTable", () => {
  it("csv: UTF-8 BOM (Arabic opens cleanly in Excel), RFC quoting", () => {
    const bytes = serializeTable(["Token", "Root"], [["الْكِتَاب", 'ka"tab']], "csv");
    // ignoreBOM:true keeps the BOM in the output (default STRIPS it).
    const text = new TextDecoder("utf-8", { ignoreBOM: true }).decode(bytes);
    expect(text.startsWith("\uFEFF")).toBe(true);
    expect(text).toContain('"الْكِتَاب"');
    expect(text).toContain('"ka""tab"');
  });

  it("tsv: BOM + tab delimiter", () => {
    const text = new TextDecoder("utf-8", { ignoreBOM: true }).decode(serializeTable(["a", "b"], [["ب", "x"]], "tsv"));
    expect(text.startsWith("\uFEFF")).toBe(true);
    expect(text).toContain("\t");
  });

  it("xlsx: HTML-table fallback escapes markup", () => {
    const text = new TextDecoder().decode(serializeTable(["h"], [["<b>&"]], "xlsx"));
    expect(text).toContain("<table");
    expect(text).toContain("&lt;b&gt;&amp;");
  });

  it("json: {headers, rows} passthrough", () => {
    const text = new TextDecoder().decode(serializeTable(["a"], [["1"]], "json"));
    expect(JSON.parse(text)).toEqual({ headers: ["a"], rows: [["1"]] });
  });

  it("flattenDataToTable: array of objects → columns from first row", () => {
    const t = flattenDataToTable([{ a: 1, b: "x" }, { a: 2, b: "y" }]);
    expect(t.headers).toEqual(["a", "b"]);
    expect(t.rows).toEqual([["1", "x"], ["2", "y"]]);
  });

  it("concordanceLinesToTable: reading order with document + line id", () => {
    const t = concordanceLinesToTable([
      {
        line_id: "d1-0-5", document_id: "d1", document_filename: "doc1.txt",
        sentence_idx: 0, token_idx: 5, left: "the", node: "risk", right: "of",
        pos: "NOUN", lemma: "risk",
      },
    ]);
    expect(t.headers).toEqual(["Left context", "Node", "Right context", "POS", "Lemma", "Document", "Line ID"]);
    expect(t.rows).toEqual([["the", "risk", "of", "NOUN", "risk", "doc1.txt", "d1-0-5"]]);
  });
});

// --------------------------------------------------------------------- //
// 1c. Arabic Tools: the Export dropdown appears and produces the download
// --------------------------------------------------------------------- //

describe("Arabic Tools export (v1.2.13-1)", () => {
  let anchorSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    cleanup();
    anchorSpy = vi.fn();
    (globalThis as any).URL.createObjectURL = vi.fn(() => "blob:mock");
    (globalThis as any).URL.revokeObjectURL = vi.fn();
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string, opts?: any) => {
      const el = origCreate(tag as any, opts);
      if (tag === "a") (el as any).click = anchorSpy;
      return el;
    });
    (globalThis as any).fetch = vi.fn((url: string) => {
      const u = String(url);
      if (u.includes("/arabic/backends")) return Promise.resolve(okJson({ backends: [{ name: "camel", available: true, model: "calima-msa-r13", version: "1" }] }));
      if (u.includes("/arabic/data/install/status")) return Promise.resolve(okJson({ camel_tools: { morphology_dbs: { msa: true, egy: false, glf: false, lev: false } } }));
      if (u.includes("/arabic/analyze")) {
        return Promise.resolve(okJson({
          backend: "camel", model: "calima-msa-r13",
          tokens: [{ text: "الطلاب", root: "طلب", pattern: "فاعل", lemma: "طالب", pos: "noun", stem: "طلاب", buckwalter: "AlTAlAb" }],
          n_tokens: 1, elapsed_ms: 1,
        }));
      }
      return Promise.resolve(okJson({}));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it("run analysis → Export menu → CSV download attempt with arabic_morphology.csv", async () => {
    const { getByRole, getByText } = render(
      <QueryClientProvider client={makeClient()}>
        <ArabicView />
      </QueryClientProvider>,
    );
    fireEvent.click(getByRole("button", { name: /Run analysis/ }));
    await waitFor(() => expect(getByText("الطلاب")).toBeTruthy());
    // Export dropdown opens and lists the five data formats
    fireEvent.click(getByRole("button", { name: /Export/ }));
    // Menu entries are plain <button>s inside role="menu" (ExportButton.tsx)
    fireEvent.click(getByRole("button", { name: /CSV/ }));
    await waitFor(() => expect(anchorSpy).toHaveBeenCalled());
    // The anchor was configured as a download of the per-tool filename
    const anchor = anchorSpy.mock.instances[0] as HTMLAnchorElement;
    expect(anchor.download).toBe("arabic_morphology.csv");
  });

  it("no Export button before a result exists", () => {
    const { queryByRole } = render(
      <QueryClientProvider client={makeClient()}>
        <ArabicView />
      </QueryClientProvider>,
    );
    expect(queryByRole("button", { name: /Export/ })).toBeNull();
  });
});

// --------------------------------------------------------------------- //
// 2. CQL query mode (Concordancer)
// --------------------------------------------------------------------- //

const CQL_LINE = {
  line_id: "d1-0-3", document_id: "d1", document_filename: "doc1.txt",
  sentence_idx: 0, token_idx: 3, left: "they", node: "take", right: "the risk",
  pos: "VERB", lemma: "take",
};

describe("Concordancer CQL mode (v1.2.13-1)", () => {
  beforeEach(() => {
    cleanup();
    useApp.setState({ activeCorpusId: "c1" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  function mount() {
    return render(
      <QueryClientProvider client={makeClient()}>
        <ConcordancerView />
      </QueryClientProvider>,
    );
  }

  it("CQL search hits /concordance/cql and renders through the KWIC table", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith("/corpora/c1")) return Promise.resolve(okJson({ id: "c1", language: "en", name: "T" }));
      if (u.endsWith("/concordance/cql")) {
        return Promise.resolve(okJson({
          lines: [CQL_LINE], total: 1,
          query: { q: init && JSON.parse(String(init.body)).query, mode: "cql", window: 5, within: null },
        }));
      }
      return Promise.resolve(okJson({}));
    });
    (globalThis as any).fetch = fetchMock;

    const { getByRole, getByText, getAllByText, container } = mount();
    fireEvent.click(getByRole("button", { name: "CQL" }));
    fireEvent.change(getByRole("textbox"), { target: { value: '[lemma="take"] []{0,3} "risk"' } });
    fireEvent.click(getByRole("button", { name: "Search" }));

    await waitFor(() => expect(getByText('[lemma="take"] []{0,3} "risk"')).toBeTruthy());
    expect(container.textContent).toContain("for CQL");
    // "take" appears as the node AND the lemma cell
    expect(getAllByText("take").length).toBeGreaterThanOrEqual(2);
    expect(getByText("the risk")).toBeTruthy();
    expect(getByText("doc1.txt")).toBeTruthy();
    // Simple-mode-only controls are hidden in CQL mode: exactly ONE select
    // remains — the KWIC sort-level picker (sort IS supported by the CQL
    // endpoint); the LEVELS (word/lemma/…) select is gone.
    const selects = container.querySelectorAll("select");
    expect(selects).toHaveLength(1);
    expect((selects[0] as HTMLSelectElement).title).toContain("sort level");
    // the endpoint was called with the CQL payload
    const cqlCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/concordance/cql"));
    expect(cqlCall).toBeTruthy();
    const body = JSON.parse(String(cqlCall![1]?.body ?? "{}"));
    expect(body.query).toBe('[lemma="take"] []{0,3} "risk"');
  });

  it("invalid pattern: shows the engine's position-annotated 422 detail", async () => {
    (globalThis as any).fetch = vi.fn((url: string) => {
      const u = String(url);
      if (u.endsWith("/corpora/c1")) return Promise.resolve(okJson({ id: "c1", language: "en", name: "T" }));
      if (u.endsWith("/concordance/cql")) {
        return Promise.resolve(okJson(
          { detail: 'Invalid CQL query: syntax error at position 5: unexpected end of query' },
          422,
        ));
      }
      return Promise.resolve(okJson({}));
    });

    const { getByRole, container } = mount();
    fireEvent.click(getByRole("button", { name: "CQL" }));
    fireEvent.change(getByRole("textbox"), { target: { value: '[lemma="take"' } });
    fireEvent.click(getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(container.textContent).toContain("Invalid CQL query: syntax error at position 5"),
    );
    // rendered inside the alert error block (not a raw HTTP/JSON dump)
    expect(getByRole("alert").textContent).toContain("Invalid CQL query");
  });
});
