/**
 * Analysis -- frequency, collocation, keyness, dispersion, n-grams, POS,
 * grammar, dependency, discourse, vocabulary, sentiment, metaphor.
 *
 * The active sub-tab is driven by the sidebar navigation (activeNav in
 * the UI store). When the user clicks "Frequency" in the sidebar, this
 * view receives "frequency" as the active tab and renders that panel.
 * The internal tab bar also allows switching between analyses.
 */
import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api, exportWithFeedback, type ExportFormat, type ReferenceCorpusEntry, type POSAnalysisResult, type SemanticAnalysisResult } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI, type NavTarget } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";
import { ExportButton } from "@/components/ExportButton";
import { CollocationNetwork } from "@/components/CollocationNetwork";

// Issue 5: shared export-status hook so every analysis panel gets the same
// user-visible success/error feedback without duplicating the boilerplate.
function useExportStatus() {
  const [status, setStatus] = useState<{ kind: "success" | "error" | "info"; msg: string } | null>(null);
  const set = (msg: string, kind: "success" | "error" | "info" = "info") => {
    setStatus({ kind, msg });
    if (msg) setTimeout(() => setStatus(null), 8000);
  };
  const el = status && status.msg ? (
    <div className={clsx("uploader-status", status.kind)} style={{ marginTop: "var(--space-2)" }}>
      {status.msg}
    </div>
  ) : null;
  return { set, el };
}

// Issue 5: helper for panels that export client-side result data (no
// backend round-trip — the data is already in `result.data`). Now properly
// serializes to the chosen format (xlsx/csv/tsv/txt/json) instead of always
// dumping JSON regardless of format.
async function downloadJsonResult(
  data: unknown,
  filename: string,
  setStatus: (msg: string, kind: "success" | "error" | "info") => void,
) {
  const { exportWithFeedback } = await import("@/lib/api");
  // Extract the extension from the filename to determine format
  const ext = filename.split(".").pop()?.toLowerCase() || "json";
  // Convert the data to the requested format
  let blob: Blob;
  if (ext === "json") {
    blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  } else {
    // For xlsx/csv/tsv/txt, flatten the data to a table and serialize client-side
    const { rows, headers } = flattenDataToTable(data);
    const serialized = serializeTable(headers, rows, ext);
    const mimeType = ext === "xlsx"
      ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      : ext === "csv"
      ? "text/csv; charset=utf-8"
      : ext === "tsv"
      ? "text/tab-separated-values; charset=utf-8"
      : "text/plain; charset=utf-8";
    blob = new Blob([serialized as unknown as ArrayBuffer], { type: mimeType });
  }
  await exportWithFeedback(
    async () => blob,
    filename,
    setStatus,
  );
}

/** Flatten an arbitrary result object into a table (headers + rows) for export. */
function flattenDataToTable(data: unknown): { headers: string[]; rows: string[][] } {
  if (Array.isArray(data)) {
    // Array of objects — extract headers from first element
    if (data.length === 0) return { headers: [], rows: [] };
    const first = data[0];
    if (typeof first === "object" && first !== null) {
      const headers = Object.keys(first);
      const rows = data.map((item) => headers.map((h) => String((item as any)[h] ?? "")));
      return { headers, rows };
    }
    // Array of primitives
    return { headers: ["value"], rows: data.map((v) => [String(v)]) };
  }
  if (typeof data === "object" && data !== null) {
    // Single object — try to find array properties and export those
    const obj = data as Record<string, unknown>;
    for (const key of Object.keys(obj)) {
      if (Array.isArray(obj[key]) && obj[key].length > 0 && typeof obj[key][0] === "object") {
        const headers = Object.keys(obj[key][0] as object);
        const rows = (obj[key] as unknown[]).map((item) =>
          headers.map((h) => String((item as Record<string, unknown>)[h] ?? "")),
        );
        return { headers, rows };
      }
    }
    // No arrays found — export key/value pairs
    const headers = ["key", "value"];
    const rows = Object.entries(obj).map(([k, v]) => [k, String(v)]);
    return { headers, rows };
  }
  return { headers: ["value"], rows: [[String(data)]] };
}

/** Serialize a table to the requested format (client-side, no backend needed). */
function serializeTable(headers: string[], rows: string[][], fmt: string): Uint8Array {
  if (fmt === "csv" || fmt === "tsv") {
    const delim = fmt === "csv" ? "," : "\t";
    const lines = [headers.join(delim)];
    for (const row of rows) {
      lines.push(row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(delim));
    }
    // Add UTF-8 BOM for Excel compatibility
    const text = "\uFEFF" + lines.join("\n");
    return new TextEncoder().encode(text);
  }
  if (fmt === "txt") {
    // Fixed-width text
    const widths = headers.map((h, i) =>
      Math.max(h.length, ...rows.map((r) => String(r[i] ?? "").length)),
    );
    const lines = [
      headers.map((h, i) => h.padEnd(widths[i])).join(""),
      "-".repeat(widths.reduce((a, b) => a + b, 0)),
      ...rows.map((r) => r.map((cell, i) => String(cell).padEnd(widths[i])).join("")),
    ];
    return new TextEncoder().encode(lines.join("\n"));
  }
  if (fmt === "xlsx") {
    // Use openpyxl-style XML (minimal XLSX) — or fall back to CSV with .xlsx extension
    // Since we can't generate real XLSX in the browser without a library,
    // generate an HTML table that Excel can open, with the .xlsx extension.
    // The user gets a file that opens in Excel. Not ideal, but better than JSON.
    const lines = [
      '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">',
      "<head><meta charset=\"utf-8\"></head><body><table border=\"1\">",
      "<tr>" + headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("") + "</tr>",
      ...rows.map((r) => "<tr>" + r.map((c) => `<td>${escapeHtml(c)}</td>`).join("") + "</tr>"),
      "</table></body></html>",
    ];
    return new TextEncoder().encode(lines.join(""));
  }
  // Default: JSON
  return new TextEncoder().encode(JSON.stringify({ headers, rows }, null, 2));
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

type Tab =
  | "frequency" | "collocation" | "keyness" | "dispersion"
  | "ngrams" | "pos" | "grammar" | "dep" | "discourse" | "vocab" | "sentiment" | "metaphor"
  | "documents" | "readability" | "groups"
  // v1.2.0: semantic concordancing (Anthony 2025) lives in the Analysis shell.
  | "vector";

const NAV_TO_TAB: Record<string, Tab> = {
  frequency: "frequency",
  "vector-kwic": "vector", // v1.2.0: sidebar entry lands on the Vector KWIC tab
  collocation: "collocation",
  keyness: "keyness",
  dispersion: "dispersion",
  ngrams: "ngrams",
  pos: "pos",
  grammar: "grammar",
  dependency: "dep",
  discourse: "discourse",
  vocab: "vocab",
  sentiment: "sentiment",
  metaphor: "metaphor",
};

// ---------------------------------------------------------------------------
// v1.2.3 — Analysis tool CARDS (replace the flat text tab strip).
//
// - Order mirrors the sidebar “Analyze” group EXACTLY (Concordance first,
//   then Vector KWIC … Metaphor), so the top strip and the sidebar never
//   disagree. Concordance renders its own view, so its card simply jumps
//   there (same as clicking it in the sidebar).
// - Documents / Readability / Compare groups have NO sidebar entry (they are
//   reachable only from this shell), so they trail after the sidebar tools.
// - Icons are the same glyphs the sidebar uses; hues come from an 8-color
//   theme-matched palette (tool-hue-1…8 in global.css, light + dark values).
// - Clicking a card also syncs the sidebar highlight (setActiveNav) so the
//   two navigation surfaces stay in lockstep.
// - Labels reuse the sidebar i18n keys, so the strip is bilingual like the
//   rest of the app (the old tab strip was English-only).
// ---------------------------------------------------------------------------
interface ToolCard {
  /** AnalysisView tab to activate (null for the Concordance jump card). */
  id: Tab | null;
  /** Sidebar counterpart whose highlight should follow the card. */
  nav: NavTarget | null;
  labelKey?: TranslationKey;
  label?: string; // fallback for tools without a sidebar i18n key
  icon: string;
  hue: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
}

const TOOL_CARDS: ToolCard[] = [
  { id: null, nav: "concordance", labelKey: "nav_concordance", icon: "\u2727", hue: 1 },
  { id: "vector", nav: "vector-kwic", labelKey: "nav_vector_kwic", icon: "\u2739", hue: 2 },
  { id: "frequency", nav: "frequency", labelKey: "nav_frequency", icon: "\u2111", hue: 3 },
  { id: "collocation", nav: "collocation", labelKey: "nav_collocation", icon: "\u2726", hue: 4 },
  { id: "keyness", nav: "keyness", labelKey: "nav_keyness", icon: "\u2605", hue: 5 },
  { id: "dispersion", nav: "dispersion", labelKey: "nav_dispersion", icon: "\u2234", hue: 6 },
  { id: "ngrams", nav: "ngrams", labelKey: "nav_ngrams", icon: "\u224B", hue: 7 },
  { id: "pos", nav: "pos", labelKey: "nav_pos", icon: "\u2135", hue: 8 },
  { id: "grammar", nav: "grammar", labelKey: "nav_grammar", icon: "\u2699", hue: 1 },
  { id: "dep", nav: "dependency", labelKey: "nav_dependency", icon: "\u2192", hue: 4 },
  { id: "discourse", nav: "discourse", labelKey: "nav_discourse", icon: "\u201D", hue: 5 },
  { id: "vocab", nav: "vocab", labelKey: "nav_vocab", icon: "\u4E00", hue: 6 },
  { id: "sentiment", nav: "sentiment", labelKey: "nav_sentiment", icon: "\u263A", hue: 7 },
  { id: "metaphor", nav: "metaphor", labelKey: "nav_metaphor", icon: "\u2248", hue: 8 },
  // Corpus-level metrics — this shell only (no sidebar entry), kept last.
  { id: "documents", nav: null, label: "Documents", icon: "\u25A4", hue: 3 },
  { id: "readability", nav: null, label: "Readability", icon: "\u25D0", hue: 1 },
  { id: "groups", nav: null, label: "Compare groups", icon: "\u21C4", hue: 2 },
];

export function AnalysisView() {
  const cid = useApp((s) => s.activeCorpusId);
  const lang = useUI((s) => s.lang);
  const activeNav = useUI((s) => s.activeNav);
  const setActiveNav = useUI((s) => s.setActiveNav);
  const [tab, setTab] = useState<Tab>("frequency");

  // Sync the internal tab with the sidebar navigation
  useEffect(() => {
    const mapped = NAV_TO_TAB[activeNav];
    if (mapped) setTab(mapped);
  }, [activeNav]);

  if (!cid) return <div className="empty-state">Select a corpus to analyze. Go to <strong>Corpora Selection → Your Corpus</strong> in the sidebar to create a corpus and upload texts.</div>;

  const onCard = (c: ToolCard) => {
    if (c.id === null) {
      // Concordance card → jump to the dedicated concordancer view (the
      // sidebar's first Analyze entry); App routes it to ConcordancerView.
      setActiveNav("concordance");
      return;
    }
    setTab(c.id);
    // Keep the sidebar highlight in lockstep with the cards.
    if (c.nav && c.nav !== activeNav) setActiveNav(c.nav);
  };

  return (
    <div className="analysis">
      <div className="tool-cards" role="tablist" aria-label={lang === "ar" ? "أدوات التحليل" : "Analysis tools"}>
        {TOOL_CARDS.map((c) => {
          const active = c.id !== null && tab === c.id;
          return (
            <button
              key={c.labelKey ?? c.label}
              className={clsx("tool-card", `tool-hue-${c.hue}`, { active })}
              role="tab"
              aria-selected={active}
              onClick={() => onCard(c)}
            >
              <span className="tool-card-icon" aria-hidden="true">{c.icon}</span>
              <span className="tool-card-label">{c.labelKey ? t(lang, c.labelKey) : c.label}</span>
            </button>
          );
        })}
      </div>

      {tab === "frequency" && <FrequencyPanel cid={cid} />}
      {tab === "vector" && <VectorKwicPanel cid={cid} />}
      {tab === "collocation" && <CollocationPanel cid={cid} />}
      {tab === "keyness" && <KeynessPanel cid={cid} />}
      {tab === "dispersion" && <DispersionPanel cid={cid} />}
      {tab === "ngrams" && <NGramsPanel cid={cid} />}
      {tab === "pos" && <POSPanel cid={cid} />}
      {tab === "grammar" && <GrammarPanel cid={cid} />}
      {tab === "dep" && <DependencyPanel cid={cid} />}
      {tab === "discourse" && <DiscoursePanel cid={cid} />}
      {tab === "vocab" && <VocabPanel cid={cid} />}
      {tab === "sentiment" && <SentimentPanel cid={cid} />}
      {tab === "metaphor" && <MetaphorPanel cid={cid} />}
      {tab === "documents" && <DocumentStatsPanel cid={cid} />}
      {tab === "readability" && <ReadabilityPanelView cid={cid} />}
      {tab === "groups" && <GroupFrequencyPanel cid={cid} />}
    </div>
  );
}


function FrequencyPanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  const [unit, setUnit] = useState<"word" | "lemma" | "pos" | "root" | "pattern">("word");
  const [minFreq, setMinFreq] = useState(1);
  const [stopwordListId, setStopwordListId] = useState<string | null>(null);
  // v1.2.0: Arabic normalization (alef/ya/ta-marbuta unification + dediac) before aggregation.
  const [normalizeArabic, setNormalizeArabic] = useState(false);
  // v1.0.1: optional stopword filter
  const stopwordLists = useQuery({
    queryKey: ["stopword-lists"],
    queryFn: () => api.stopwordLists.list(),
  });
  const result = useQuery({
    queryKey: ["frequency", cid, unit, minFreq, stopwordListId, normalizeArabic],
    queryFn: () => api.frequency(cid, unit, minFreq, 200, false, stopwordListId, normalizeArabic),
  });

  const exportStatus = useExportStatus();

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    await exportWithFeedback(
      () => api.exportFrequency(cid, unit, fmt as ExportFormat, 1000),
      `frequency_${unit}.${fmt}`,
      exportStatus.set,
    );
  };

  const div = result.data?.lexical_diversity;

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Unit
          <select value={unit} onChange={(e) => setUnit(e.target.value as any)}>
            <option value="word">Word</option>
            <option value="lemma">Lemma</option>
            <option value="pos">POS tag</option>
            <option value="root">Root (Arabic)</option>
            <option value="pattern">Pattern (Arabic)</option>
          </select>
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <label title="Exclude function words from the list and the totals">
          Stopwords
          <select value={stopwordListId ?? ""} onChange={(e) => setStopwordListId(e.target.value || null)}>
            <option value="">- None -</option>
            {(stopwordLists.data?.items ?? []).map((sw) => (
              <option key={sw.id} value={sw.id}>{sw.name}</option>
            ))}
          </select>
        </label>
        <label title={t(lang, "arb_normalize_hint")}>
          <input type="checkbox" checked={normalizeArabic} onChange={(e) => setNormalizeArabic(e.target.checked)} />
          {t(lang, "arb_normalize")}
        </label>
        <ExportButton onExport={onExport} disabled={!result.data} />
      </div>
      {exportStatus.el}

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens ·
            <strong> {result.data.total_types.toLocaleString()}</strong> types
            {div && (
              <> · STTR = <strong>{div.sttr.toFixed(4)}</strong> · MATTR = <strong>{div.mattr.toFixed(4)}</strong> ·{" "}
                MTLD = <strong>{div.mtld.toFixed(2)}</strong> · Guiraud = <strong>{div.guiraud.toFixed(3)}</strong>
              </>
            )}
          </div>
          <DataTable
            headers={[unit, "Frequency", "Per million", "%", "Range", "Range %"]}
            rows={result.data.rows.map((r) => [r.item, r.freq, r.per_million, r.percent, r.range, r.range_percent ?? "—"])}
          />
          <div className="hint" style={{ marginTop: "var(--space-2)" }}>
            Range = number of documents containing the item; Range % = share of documents in scope.
          </div>
        </>
      )}
    </div>
  );
}


function CollocationPanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  const [node, setNode] = useState("");
  const [level, setLevel] = useState<"word" | "lemma">("lemma");
  const [window, setWindow] = useState(5);
  const [spanLeft, setSpanLeft] = useState<number | null>(null);
  const [spanRight, setSpanRight] = useState<number | null>(null);
  const [posExclude, setPosExclude] = useState<string>("");
  const [stopwordListId, setStopwordListId] = useState<string | null>(null);
  const [minFreq, setMinFreq] = useState(3);
  // v1.2.0: Arabic normalization toggle, folded into the submitted snapshot.
  const [normalizeArabic, setNormalizeArabic] = useState(false);
  const [submitted, setSubmitted] = useState<{ n: string; l: string; w: number; mf: number; sl: number | null; sr: number | null; pe: string[]; sw: string | null; nm: boolean } | null>(null);

  const stopwordLists = useQuery({
    queryKey: ["stopword-lists"],
    queryFn: () => api.stopwordLists.list(),
  });

  const result = useQuery({
    queryKey: ["collocations", cid, submitted],
    queryFn: () => api.collocations(cid, submitted!.n, submitted!.l as any, submitted!.w, submitted!.mf, undefined, 100, {
      span_left: submitted!.sl, span_right: submitted!.sr,
      pos_exclude: submitted!.pe.length ? submitted!.pe : null,
      stopword_list_id: submitted!.sw,
      normalize_arabic: submitted!.nm,
    }),
    enabled: !!submitted,
  });

  const onSearch = () => {
    if (!node.trim()) return;
    setSubmitted({
      n: node.trim(), l: level, w: window, mf: minFreq,
      sl: spanLeft, sr: spanRight,
      pe: posExclude.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean),
      sw: stopwordListId,
      nm: normalizeArabic,
    });
  };

  const exportStatus = useExportStatus();

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!submitted) return;
    if (fmt === "svg") {
      await exportWithFeedback(
        () => api.exportCollocationNetworkSvg(cid, submitted.n, submitted.l as any, submitted.w, submitted.mf),
        `collocation_network_${submitted.n}.svg`,
        exportStatus.set,
      );
    } else if (fmt === "png") {
      await exportWithFeedback(
        () => api.exportCollocationNetworkPng(cid, submitted.n, submitted.l as any, submitted.w, submitted.mf),
        `collocation_network_${submitted.n}.png`,
        exportStatus.set,
      );
    } else {
      await exportWithFeedback(
        () => api.exportCollocations(cid, submitted.n, fmt, submitted.l as any, submitted.w, submitted.mf),
        `collocations_${submitted.n}.${fmt}`,
        exportStatus.set,
      );
    }
  };

  // Determine which measure columns to show
  const measureKeys = result.data?.rows[0]
    ? Object.keys(result.data.rows[0]).filter((k) =>
        !["collocate", "O", "fx", "fy", "N"].includes(k))
    : [];

  return (
    <div className="panel-content">
      <div className="toolbar">
        <input
          type="text"
          value={node}
          onChange={(e) => setNode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="Node word (e.g. 'fox')"
        />
        <label>Level
          <select value={level} onChange={(e) => setLevel(e.target.value as any)}>
            <option value="lemma">Lemma</option>
            <option value="word">Word</option>
          </select>
        </label>
        <label>Window
          <input type="number" min={1} max={20} value={window}
                 onChange={(e) => setWindow(Number(e.target.value))} />
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq}
                 onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <label title="Left span (blank = symmetric window)">L-span
          <input type="number" min={0} max={20} value={spanLeft ?? ""}
                 placeholder={String(window)}
                 onChange={(e) => setSpanLeft(e.target.value === "" ? null : Number(e.target.value))} />
        </label>
        <label title="Right span (blank = symmetric window)">R-span
          <input type="number" min={0} max={20} value={spanRight ?? ""}
                 placeholder={String(window)}
                 onChange={(e) => setSpanRight(e.target.value === "" ? null : Number(e.target.value))} />
        </label>
        <label title="Exclude collocates with these UPOS tags (prefix match)">Exclude POS
          <input type="text" value={posExclude} onChange={(e) => setPosExclude(e.target.value)}
                 placeholder="e.g. DET ADP" style={{ width: 90 }} />
        </label>
        <label title="Exclude stopword-list items from the collocate pool">Stopwords
          <select value={stopwordListId ?? ""} onChange={(e) => setStopwordListId(e.target.value || null)}>
            <option value="">- None -</option>
            {(stopwordLists.data?.items ?? []).map((sw) => (
              <option key={sw.id} value={sw.id}>{sw.name}</option>
            ))}
          </select>
        </label>
        <label title={t(lang, "arb_normalize_hint")}>
          <input type="checkbox" checked={normalizeArabic} onChange={(e) => setNormalizeArabic(e.target.checked)} />
          {t(lang, "arb_normalize")}
        </label>
        <button onClick={onSearch} disabled={!node.trim()}>Compute</button>
        <ExportButton onExport={onExport} disabled={!result.data} />
        <ExportButton
          label="Export diagram"
          onExport={onExport}
          disabled={!result.data}
          formats={["svg", "png"]}
        />
      </div>

      <div className="grounding-notice">
        <strong>Reproducibility:</strong> every collocation result carries its window size
        and minimum frequency. A collocation measure without a stated window is not reproducible.
        All measures use the formulas in <code>docs/METHODOLOGY.md</code>.
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Node: <code>{result.data.node}</code> · Spans {result.data.span_left}/{result.data.span_right} · Min freq {result.data.min_freq}
            · Marginals: whole-corpus (folded)
          </div>
          {(result.data.warnings ?? []).map((w, i) => (
            <div key={i} className="keyness-min-tokens-warning" role="status">⚠ {w}</div>
          ))}
          {result.data.rows.length === 0 ? (
            <div className="empty-state">No collocates met the min-frequency threshold.</div>
          ) : (
            <>
              <DataTable
                headers={["Collocate", "O", "f(node)", "f(y)", "N", ...measureKeys]}
                rows={result.data.rows.map((r) => [
                  r.collocate, r.O, r.fx, r.fy, r.N,
                  ...measureKeys.map((k) => (r as any)[k] ?? "—"),
                ])}
              />
              <CollocationNetwork
                cid={cid}
                centerNode={result.data.node}
                level={submitted!.l as "word" | "lemma"}
                window={submitted!.w}
                minFreq={submitted!.mf}
                onSetCenter={(word) => { setNode(word); setSubmitted({ n: word, l: level, w: window, mf: minFreq, sl: spanLeft, sr: spanRight, pe: posExclude.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean), sw: stopwordListId, nm: normalizeArabic }); }}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}




function KeynessPanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  const referenceCorpusId = useApp((s) => s.referenceCorpusId);
  const setReferenceCorpus = useApp((s) => s.setReferenceCorpus);
  const selectedReferenceName = useApp((s) => s.selectedReferenceName);
  const [minFreq, setMinFreq] = useState(5);
  const [stopwordListId, setStopwordListId] = useState<string | null>(null);
  // v1.2.0: Arabic normalization for the engine-corpus keyness path (bundled
  // frequency lists are pre-normalized upstream, so the flag only applies to
  // the /keyness endpoint).
  const [normalizeArabic, setNormalizeArabic] = useState(false);
  const stopwordLists = useQuery({
    queryKey: ["stopword-lists"],
    queryFn: () => api.stopwordLists.list(),
  });

  // Need to list corpora in the active project to populate the reference picker
  const activeProjectId = useApp((s) => s.activeProjectId);
  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => api.listCorpora(activeProjectId!),
    enabled: !!activeProjectId,
  });

  // v0.1.17: also fetch the list of installed bundled references
  const refCorpora = useQuery({
    queryKey: ["reference-corpora"],
    queryFn: () => api.listReferenceCorpora(),
  });

  // Use the uploaded reference corpus if set, otherwise the selected bundled reference
  const result = useQuery({
    queryKey: ["keyness", cid, referenceCorpusId, selectedReferenceName, minFreq, stopwordListId, normalizeArabic],
    queryFn: () => {
      if (referenceCorpusId) {
        return api.keyness(cid, referenceCorpusId, minFreq, 200, stopwordListId, normalizeArabic);
      } else if (selectedReferenceName) {
        return api.keynessWithReference(cid, selectedReferenceName, minFreq, 200) as any;
      }
      throw new Error("No reference selected");
    },
    enabled: !!referenceCorpusId || !!selectedReferenceName,
  });

  const exportStatus = useExportStatus();

  // Issue #3: Surface min_corpus_tokens as a non-blocking warning. The target
  // corpus's token count is already available from its stats (populated by the
  // backend on every ingestion). The selected reference's min_corpus_tokens
  // comes from ReferenceCorpusSpec for bundled references; for user-uploaded
  // reference corpora we fall back to the ReferenceCorpusSpec default of 1,000
  // tokens (registry.py). Small-N reference frequencies produce statistically
  // unstable, easily-inflated log-likelihood scores, so we warn the user --
  // but never block the comparison (matches the spec's stated intent).
  const targetTokenCount = corpora.data?.find((c) => c.id === cid)?.stats?.token_count ?? 0;
  const selectedBundledRef = refCorpora.data?.references.find(
    (r: ReferenceCorpusEntry) => r.name === selectedReferenceName,
  );
  // Bundled references carry their own min_corpus_tokens; uploaded reference
  // corpora use the ReferenceCorpusSpec default of 1,000.
  const minTokensForSelected = selectedBundledRef?.min_corpus_tokens ?? 1_000;
  const showMinTokensWarning =
    targetTokenCount > 0 &&
    targetTokenCount < minTokensForSelected &&
    (!!referenceCorpusId || !!selectedReferenceName);

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (referenceCorpusId) {
      await exportWithFeedback(
        () => api.exportKeyness(cid, referenceCorpusId, fmt as ExportFormat),
        `keyness.${fmt}`,
        exportStatus.set,
      );
    } else if (selectedReferenceName) {
      // For bundled references, export the keyness result as JSON
      const data = result.data;
      if (data) {
        await downloadJsonResult(data, `keyness_vs_${selectedReferenceName}.${fmt}`, exportStatus.set);
      }
    }
  };

  const onMethodsPdf = async () => {
    await exportWithFeedback(
      () => api.exportMethodsPdf(cid),
      `methods_section.pdf`,
      exportStatus.set,
    );
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Reference corpus
          <select value={referenceCorpusId ?? ""} onChange={(e) => setReferenceCorpus(e.target.value || null)}>
            <option value="">- Select uploaded corpus -</option>
            {corpora.data?.filter((c) => c.id !== cid).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        {/* v0.1.17: also show installed bundled reference frequency lists */}
        {refCorpora.data?.references.filter((r: ReferenceCorpusEntry) => r.installed).length ?? 0 > 0 ? (
          <label>or bundled reference
            <select
              value={selectedReferenceName ?? ""}
              onChange={(e) => useApp.getState().setSelectedReferenceName(e.target.value || null)}
              disabled={!!referenceCorpusId}
            >
              <option value="">- None -</option>
              {refCorpora.data?.references.filter((r: ReferenceCorpusEntry) => r.installed).map((r: ReferenceCorpusEntry) => (
                <option key={r.name} value={r.name}>{r.display_name}</option>
              ))}
            </select>
          </label>
        ) : null}
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <label title="Exclude stopword-list items from both target and reference">
          Stopwords
          <select value={stopwordListId ?? ""} onChange={(e) => setStopwordListId(e.target.value || null)}>
            <option value="">- None -</option>
            {(stopwordLists.data?.items ?? []).map((sw) => (
              <option key={sw.id} value={sw.id}>{sw.name}</option>
            ))}
          </select>
        </label>
        <label title={t(lang, "arb_normalize_hint")}>
          <input type="checkbox" checked={normalizeArabic} onChange={(e) => setNormalizeArabic(e.target.checked)} />
          {t(lang, "arb_normalize")}
        </label>
        <ExportButton onExport={onExport} disabled={!result.data} />
        <button onClick={onMethodsPdf}>Methods PDF</button>
      </div>
      {exportStatus.el}

      {showMinTokensWarning && (
        <div className="keyness-min-tokens-warning" role="status">
          <strong>Heads up:</strong> your target corpus has{" "}
          {targetTokenCount.toLocaleString()} tokens, below the recommended
          minimum of {minTokensForSelected.toLocaleString()} for this
          reference. Keyness scores from small-N comparisons can be
          statistically unstable (easily inflated log-likelihood values);
          interpret with care, or upload a larger target corpus.
        </div>
      )}

      <div className="grounding-notice">
        <strong>4 Principle 3:</strong> a "key" word is never reported as important on
        frequency-of-occurrence-in-a-huge-corpus grounds alone. Log Ratio, %DIFF,
        Simple Maths, and Odds Ratio ride alongside log-likelihood - never report
        one without the other.
      </div>

      {(result.data as any)?.warnings?.map((w: string, i: number) => (
        <div key={i} className="keyness-min-tokens-warning" role="status">⚠ {w}</div>
      ))}

      {result.data && (
        <>
          <div className="result-meta">
            Target N₁ = <strong>{result.data.N1.toLocaleString()}</strong> ·
            Reference N₂ = <strong>{result.data.N2.toLocaleString()}</strong>
          </div>
          <h3>Positive keywords (over-represented in target)</h3>
          <DataTable
            headers={["Term", "f1", "f2", "LL", "χ²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio"]}
            rows={(result.data as any).positive_keywords.map((r: any) => [
              r.term, r.f1, r.f2, fmt(r.log_likelihood), fmt(r.chi_square),
              fmt(r.log_ratio), fmt(r.pct_diff), fmt(r.simple_maths), fmt(r.odds_ratio),
            ])}
          />
          <h3>Negative keywords (under-represented in target)</h3>
          <DataTable
            headers={["Term", "f1", "f2", "LL", "χ²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio"]}
            rows={(result.data as any).negative_keywords.map((r: any) => [
              r.term, r.f1, r.f2, fmt(r.log_likelihood), fmt(r.chi_square),
              fmt(r.log_ratio), fmt(r.pct_diff), fmt(r.simple_maths), fmt(r.odds_ratio),
            ])}
          />
        </>
      )}
    </div>
  );
}


function DispersionPanel({ cid }: { cid: string }) {
  const [term, setTerm] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const result = useQuery({
    queryKey: ["dispersion", cid, submitted],
    queryFn: () => api.dispersion(cid, submitted!, "word"),
    enabled: !!submitted,
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      <div className="toolbar">
        <input
          type="text"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setSubmitted(term.trim())}
          placeholder="Term (e.g. 'the')"
        />
        <button onClick={() => setSubmitted(term.trim())} disabled={!term.trim()}>Compute</button>
        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `dispersion.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      {exportStatus.el}

      {result.data && (
        <>
          <div className="result-meta">
            Juilland's D = <strong>{result.data.juillands_d}</strong> · Gries' DP = <strong>{result.data.gries_dp}</strong> ·{" "}
            DP-norm = <strong>{result.data.gries_dp_norm}</strong>
            <div>Range = <strong>{result.data.range}</strong> documents ({result.data.range_percent}%)</div>
            <div className="hint">
              Juilland's D: 1 = perfectly even, 0 = maximally concentrated (assumes roughly equal-sized parts).
              Gries' DP: 0 = perfectly even, 1 = concentrated — expected proportions are weighted by document size (v1.0.1).
              DP-norm makes DP comparable across different numbers of documents.
            </div>
          </div>
          <h3>Frequency per document</h3>
          <div className="bar-chart">
            {result.data.per_part_freqs.map((f, i) => (
              <div key={i} className="bar-row">
                <span className="bar-label">Doc {i + 1}{result.data.part_sizes?.[i] != null ? ` (${result.data.part_sizes[i].toLocaleString()} tok)` : ""}</span>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${(f / Math.max(...result.data.per_part_freqs, 1)) * 100}%` }} />
                </div>
                <span className="bar-value">{f}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}


function DataTable({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filter, setFilter] = useState("");

  // Detect if a column is numeric (all non-empty values are numbers)
  const isNumeric = (col: number) => rows.length > 0 && rows.every((r) => r[col] === "" || r[col] === null || typeof r[col] === "number");

  const sorted = [...rows];
  if (sortCol !== null) {
    const numeric = isNumeric(sortCol);
    sorted.sort((a, b) => {
      const av = a[sortCol];
      const bv = b[sortCol];
      if (av === "" || av === null) return 1;
      if (bv === "" || bv === null) return -1;
      let cmp: number;
      if (numeric) {
        cmp = Number(av) - Number(bv);
      } else {
        cmp = String(av).localeCompare(String(bv));
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }

  const filtered = filter.trim()
    ? sorted.filter((r) => r.some((c) => String(c).toLowerCase().includes(filter.toLowerCase())))
    : sorted;

  const cycleSort = (col: number) => {
    if (sortCol === col && sortDir === "asc") {
      setSortDir("desc");
    } else if (sortCol === col && sortDir === "desc") {
      setSortCol(null);
      setSortDir("asc");
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  };

  return (
    <div>
      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter results..."
        style={{ marginBottom: "var(--space-2)", padding: "4px 8px", fontSize: "13px", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", inlineSize: "100%", maxWidth: "300px" }}
      />
      <table className="data-table">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={h} onClick={() => cycleSort(i)} style={{ cursor: "pointer", userSelect: "none" }}>
                {h} {sortCol === i ? (sortDir === "asc" ? "\u25B2" : "\u25BC") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {filter.trim() && <p style={{ fontSize: "12px", color: "var(--text-subtle)", marginTop: "var(--space-1)" }}>Showing {filtered.length} of {rows.length} rows</p>}
    </div>
  );
}


function fmt(v: number | null): string {
  if (v === null || v === undefined) return "—";
  if (!isFinite(v)) return v > 0 ? "∞" : "-∞";
  return v.toFixed(4);
}


// =========================================================================
// Phase 2 panels
// =========================================================================


function NGramsPanel({ cid }: { cid: string }) {
  const [n, setN] = useState(2);
  const [minFreq, setMinFreq] = useState(2);
  const [minRange, setMinRange] = useState(1);
  const result = useQuery({
    queryKey: ["ngrams", cid, n, minFreq, minRange],
    queryFn: () => api.ngrams(cid, n, minFreq, minRange, 200),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>N
          <select value={n} onChange={(e) => setN(Number(e.target.value))}>
            {[2, 3, 4, 5, 6].map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <label>Min range (distinct docs)
          <input type="number" min={1} value={minRange} onChange={(e) => setMinRange(Number(e.target.value))} />
        </label>

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `ngrams.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      {exportStatus.el}

      <div className="grounding-notice">
        <strong>Note:</strong> Lexical bundles require BOTH a minimum frequency per million words
        AND a minimum number of distinct texts - raw frequency alone is not enough to
        distinguish genuine bundles from single-text artifacts (Biber et al.).
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens ·
            N = {result.data.n} · min_freq={result.data.min_freq} · min_range={result.data.min_range}
          </div>
          <DataTable
            headers={["N-gram", "Frequency", "Per million", "Range (docs)", "Range %"]}
            rows={result.data.rows.map((r) => [r.ngram, r.freq, r.per_million, r.range, r.range_percent])}
          />
        </>
      )}
    </div>
  );
}


// v1.2.0 (Issue 4): tagset labels for the POS panel selector
const TAGSET_LABELS: Record<string, string> = {
  upos: "UD UPOS (universal)",
  ptb: "Penn Treebank",
  claws7: "CLAWS-7 (BNC standard)",
  calima: "CAMeL / Calima (native)",
  usas: "USAS semantic (experimental)",
};
const TAGSETS_EN = ["upos", "ptb", "claws7", "usas"];
const TAGSETS_AR = ["upos", "calima", "usas"];

function POSPanel({ cid }: { cid: string }) {
  const [n, setN] = useState(1);
  const [tagsetOverride, setTagsetOverride] = useState<string | null>(null);
  const corpusQ = useQuery({
    queryKey: ["corpus", cid],
    queryFn: () => api.getCorpus(cid),
  });
  const language = corpusQ.data?.language || "en";
  // Default = the per-corpus choice saved in Your Corpus (pipeline_recipe)
  const effectiveTagset =
    tagsetOverride ??
    (corpusQ.data as unknown as { pipeline_recipe?: { tagset?: string } } | undefined)
      ?.pipeline_recipe?.tagset ??
    "upos";
  const qc = useQueryClient();

  // Persist the choice so Your Corpus + future sessions default to it.
  const saveTagset = useMutation({
    mutationFn: (t: string) => api.setCorpusTagset(cid, t),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corpus", cid] }),
  });

  const isSemantic = effectiveTagset === "usas";
  const result = useQuery<POSAnalysisResult | SemanticAnalysisResult>({
    queryKey: ["pos", cid, n, effectiveTagset],
    queryFn: () =>
      isSemantic
        ? api.semanticAnalysis(cid, 100)
        : api.posAnalysis(cid, n, 2, 100, effectiveTagset),
  });
  const exportStatus = useExportStatus();
  const tagsetOptions = language === "ar" ? TAGSETS_AR : TAGSETS_EN;

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Tagset
          <select
            value={effectiveTagset}
            onChange={(e) => {
              setTagsetOverride(e.target.value);
              saveTagset.mutate(e.target.value);
            }}
            title="Choose the grammatical or semantic tagset used for this analysis"
          >
            {tagsetOptions.map((t) => (
              <option key={t} value={t}>{TAGSET_LABELS[t] ?? t}</option>
            ))}
          </select>
        </label>

        {!isSemantic && (
          <label>N
            <select value={n} onChange={(e) => setN(Number(e.target.value))}>
              <option value={1}>1 (distribution)</option>
              <option value={2}>2 (bigrams)</option>
              <option value={3}>3 (trigrams)</option>
              <option value={4}>4</option>
              <option value={5}>5</option>
            </select>
          </label>
        )}

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `pos.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>
      {exportStatus.el}

      {isSemantic && result.data && (
        <>
          <div className="result-meta">
            <strong>{(result.data as SemanticAnalysisResult).matched_tokens.toLocaleString()}</strong> of{" "}
            <strong>{(result.data as SemanticAnalysisResult).total_tokens.toLocaleString()}</strong> tokens matched ·{" "}
            {(result.data as SemanticAnalysisResult).unmatched_percent}% unmatched
          </div>
          <div className="grounding-notice">
            <strong>Note:</strong> USAS top-level semantic categories via the bundled
            Multilingual-USAS lexicon (CC BY-NC-SA; see reference-data/tagsets). Lexicon-based
            approximation — cite the USAS taxonomy in publications.
          </div>
          <h3>Semantic distribution (USAS top-level)</h3>
          <DataTable
            headers={["Category", "Description", "Frequency", "% (matched)"]}
            rows={(result.data as SemanticAnalysisResult).distribution.map((r) => [r.tag, r.label, r.freq, r.percent])}
          />
        </>
      )}

      {!isSemantic && result.data && n === 1 && (
        <>
          <div className="result-meta"><strong>{(result.data as POSAnalysisResult).total_tokens.toLocaleString()}</strong> tokens · tagset: {TAGSET_LABELS[effectiveTagset] ?? effectiveTagset}</div>
          <h3>POS distribution</h3>
          <DataTable
            headers={["POS", "Frequency", "%"]}
            rows={(result.data as POSAnalysisResult).distribution.map((r) => [r.pos, r.freq, r.percent])}
          />
        </>
      )}
      {!isSemantic && result.data && n >= 2 && (
        <>
          <div className="result-meta"><strong>{(result.data as POSAnalysisResult).total_tokens.toLocaleString()}</strong> tokens · tagset: {TAGSET_LABELS[effectiveTagset] ?? effectiveTagset}</div>
          <h3>Top POS {n}-grams</h3>
          <DataTable
            headers={["Pattern", "Frequency"]}
            rows={(result.data as POSAnalysisResult).pos_ngrams.map((r) => [r.pattern, r.freq])}
          />
        </>
      )}
    </div>
  );
}


const GRAMMAR_PATTERNS = ["passive_voice", "modal", "negation", "relative_clause", "complex_np", "tense"] as const;


function GrammarPanel({ cid }: { cid: string }) {
  const [selected, setSelected] = useState<string[]>(GRAMMAR_PATTERNS as unknown as string[]);
  const result = useQuery({
    queryKey: ["grammar", cid, selected],
    queryFn: () => api.grammar(cid, selected, 20),
  });
  const exportStatus = useExportStatus();

  const toggle = (p: string) => {
    setSelected((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]);
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Patterns</label>
        {GRAMMAR_PATTERNS.map((p) => (
          <label key={p} className="checkbox">
            <input type="checkbox" checked={selected.includes(p)} onChange={() => toggle(p)} />
            {p}
          </label>
        ))}

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `grammar.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      {exportStatus.el}

      <div className="grounding-notice">
        <strong>Note:</strong> Grammar pattern detectors are <em>dependency-parse-driven</em>,
        not regex over surface text - so they generalize across genres.
      </div>

      {result.data && (
        <>
          <h3>Counts</h3>
          <DataTable
            headers={["Pattern", "Count"]}
            rows={Object.entries(result.data.counts).map(([p, c]) => [p, c])}
          />
          {Object.entries(result.data.patterns).map(([pat, examples]) => (
            examples.length > 0 && (
              <div key={pat}>
                <h3>{pat} - examples</h3>
                <ul className="grammar-examples">
                  {examples.map((ex, i) => {
                    const verb = String(ex.verb ?? "");
                    const modal = String(ex.modal ?? "");
                    const negator = String(ex.negator ?? "");
                    const head = String(ex.head ?? "");
                    const modifiers = Array.isArray(ex.modifiers) ? ex.modifiers.map(String) : [];
                    return (
                      <li key={i}>
                        <code className="evidence-ref">{ex.evidence_id}</code>
                        {verb && <span className="ex-verb">verb: <strong>{verb}</strong></span>}
                        {modal && <span className="ex-modal">modal: <strong>{modal}</strong></span>}
                        {negator && <span>negator: <strong>{negator}</strong></span>}
                        {head && modifiers.length > 0 && <span><strong>{head}</strong> ← {modifiers.join(", ")}</span>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )
          ))}
        </>
      )}
    </div>
  );
}


function DependencyPanel({ cid }: { cid: string }) {
  const [relation, setRelation] = useState("nsubj");
  const result = useQuery({
    queryKey: ["dep", cid, relation],
    queryFn: () => api.dependencies(cid, relation, 100),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Relation
          <select value={relation} onChange={(e) => setRelation(e.target.value)}>
            <option value="nsubj">nsubj (subject)</option>
            <option value="obj">obj (object)</option>
            <option value="iobj">iobj (indirect object)</option>
            <option value="obl">obl (oblique)</option>
            <option value="amod">amod (adjectival modifier)</option>
            <option value="compound">compound</option>
          </select>
        </label>

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `dependency.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      {exportStatus.el}

      <div className="grounding-notice">
        <strong>Note:</strong> Built as thin queries over the same dependency parses already
        produced in 8.1 - not a separate pipeline.
      </div>

      {result.data && (
        <>
          <div className="result-meta">Relation: <code>{result.data.relation}</code></div>
          <DataTable
            headers={["Governor", "Dependent", "Frequency", "Example evidence IDs"]}
            rows={result.data.rows.map((r) => [r.governor, r.dependent, r.freq, r.examples.join(" · ")])}
          />
        </>
      )}
    </div>
  );
}


function DiscoursePanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  // v1.2.6: multi-taxonomy support — the lens is user-selectable and each
  // result names + cites its taxonomy. Default stays Hyland 2005.
  const [taxonomy, setTaxonomy] = useState("hyland2005");
  const result = useQuery({
    queryKey: ["discourse", cid, taxonomy],
    queryFn: () => api.discourse(cid, taxonomy),
  });
  const taxonomies = useQuery({
    queryKey: ["discourse-taxonomies", cid],
    queryFn: () => api.discourseTaxonomies(cid),
    staleTime: 5 * 60 * 1000,
  });
  const exportStatus = useExportStatus();

  const opts: Array<{ key: string; name: string }> =
    taxonomies.data?.taxonomies.map((tx) => ({ key: tx.key, name: tx.name })) ?? [
      { key: "hyland2005", name: "Hyland 2005" },
      { key: "hallidayhasan1976", name: "Halliday & Hasan 1976" },
      { key: "martinwhite2005", name: "Martin & White 2005" },
      { key: "usas", name: "CLAWS/USAS semantic tagset (top-level)" },
    ];
  const isUsas = result.data?.taxonomy_key === "usas";

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="toolbar">
        <label htmlFor="discourse-taxonomy" style={{ fontWeight: 600 }}>
          {t(lang, "discourse_taxonomy")}:{" "}
        </label>
        <select
          id="discourse-taxonomy"
          value={taxonomy}
          onChange={(e) => setTaxonomy(e.target.value)}
        >
          {opts.map((o) => (
            <option key={o.key} value={o.key}>
              {o.name}
            </option>
          ))}
        </select>
        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `discourse.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      <div className="grounding-notice">
        <strong>Note:</strong> {t(lang, "discourse_note_intro")}{" "}
        {result.data?.citation && <em>{result.data.citation}</em>}
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Taxonomy: <strong>{result.data.taxonomy}</strong> ·
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens
            {isUsas && result.data.unmatched_percent != null && (
              <> · <span title={t(lang, "discourse_unmatched_hint")}>{t(lang, "discourse_unmatched")}: <strong>{result.data.unmatched_percent}%</strong></span></>
            )}
          </div>
          {Object.entries(result.data.categories).map(([cat, info]) => (
            <div key={cat} className="discourse-cat">
              <h3>
                {cat}{" "}
                {isUsas && (info.label || info.group) && (
                  <span className="cat-meta">
                    {info.label}
                    {info.group ? ` — ${info.group}` : ""}
                  </span>
                )}
                <span className="cat-meta">freq={info.freq} · {info.per_million}/M</span>
              </h3>
              <ul className="discourse-examples">
                {info.examples.map((ex, i) => (
                  <li key={i}>
                    {ex.evidence_id && <code className="evidence-ref">{ex.evidence_id}</code>}
                    <strong>{ex.cue}</strong>
                    {ex.sentence_preview && <em>"{ex.sentence_preview}…"</em>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
    </div>
  );
}


function VocabPanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["vocab", cid],
    queryFn: () => api.vocabProfile(cid, 1, 100),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="toolbar">
        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `vocab.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      <div className="grounding-notice">
        <strong>Note:</strong> Vocabulary profiling uses an open frequency-band approximation
        (CC-0 wordlist). EVP-style CEFR wordlists carry redistribution restrictions and are
        not bundled without confirmed rights.
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens ·
            <strong>{result.data.total_types.toLocaleString()}</strong> types
          </div>
          <h3>Frequency bands</h3>
          <DataTable
            headers={["Band", "Frequency", "%"]}
            rows={result.data.bands.map((b) => [b.band, b.freq, b.percent])}
          />
          {result.data.academic_words.length > 0 && (
            <>
              <h3>Academic words (AWL)</h3>
              <DataTable
                headers={["Word", "Frequency"]}
                rows={result.data.academic_words.map((w) => [w.word, w.freq])}
              />
            </>
          )}
          {result.data.rare_words.length > 0 && (
            <>
              <h3>Rare words (frequency {"\u2264"} 1) {result.data.rare_words.length > 50 && <span style={{ fontSize: "12px", fontWeight: "normal", color: "var(--text-subtle)" }}>(showing top 50 of {result.data.rare_words.length})</span>}</h3>
              <DataTable
                headers={["Word", "Frequency"]}
                rows={result.data.rare_words.slice(0, 50).map((w) => [w.word, w.freq])}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}


function SentimentPanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["sentiment", cid],
    queryFn: () => api.sentiment(cid),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="toolbar">
        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `sentiment.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      <div className="grounding-notice">
        <strong>Note:</strong> Phase 2 uses a lexicon-based sentiment scorer. Phase 3 will swap
        in VADER or a transformers-based model behind the same interface - results stay comparable
        because the model + version is pinned per project (4 Principle 8).
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_sentences}</strong> sentences ·
            avg score = <strong>{result.data.avg_score}</strong> (-1 to +1)
          </div>
          <div className="sentiment-bars">
            <div className="bar-row">
              <span className="bar-label">Positive</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(result.data.positive / result.data.total_sentences) * 100}%`, background: "var(--bar-positive)" }} /></div>
              <span className="bar-value">{result.data.positive}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Neutral</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(result.data.neutral / result.data.total_sentences) * 100}%`, background: "var(--bar-neutral)" }} /></div>
              <span className="bar-value">{result.data.neutral}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Negative</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(result.data.negative / result.data.total_sentences) * 100}%`, background: "var(--bar-negative)" }} /></div>
              <span className="bar-value">{result.data.negative}</span>
            </div>
          </div>
          <h3>Sentiment timeline (per sentence) {result.data.timeline.length > 100 && <span style={{ fontSize: "12px", fontWeight: "normal", color: "var(--text-subtle)" }}>(showing first 100 of {result.data.timeline.length})</span>}</h3>
          <div className="sentiment-timeline">
            {result.data.timeline.slice(0, 100).map((t, i) => (
              <div key={i} className="timeline-bar"
                style={{ height: `${Math.abs(t.score) * 40 + 2}px`,
                         background: t.score > 0 ? "var(--bar-positive)" : t.score < 0 ? "var(--bar-negative)" : "var(--bar-neutral)" }}
                title={`Sent ${t.sent}: score=${t.score} (pos=${t.pos_hits}, neg=${t.neg_hits})`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}


function MetaphorPanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["metaphor", cid],
    queryFn: () => api.metaphorCandidates(cid, 50),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="toolbar">
        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `metaphor.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      <div className="grounding-notice">
        <strong>Note:</strong> These are <em>candidates only</em>.
        The LLM triages them via MIPVU decision steps (contextual vs. basic meaning,
        contrast-but-comprehensible-via-comparison test), and a <strong>human must
        verify</strong> before any candidate counts as a confirmed metaphor in export
        or statistics. Current evidence shows LLMs alone under-perform supervised
        detectors and especially struggle to filter literal false positives - the
        verification gate is not optional UI polish, it is load-bearing for validity.
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Pipeline: <strong>{result.data.pipeline}</strong> ·
            <strong>{result.data.candidates.length}</strong> candidates ·
            <strong>{result.data.verified_count}</strong> verified
          </div>
          <ul className="metaphor-candidates">
            {result.data.candidates.map((c, i) => (
              <li key={i} className="metaphor-candidate">
                <header>
                  <code className="evidence-ref">{c.evidence_id}</code>
                  <strong className="metaphor-word">{c.word}</strong>
                  <span className="metaphor-pos">({c.pos})</span>
                  <span className="metaphor-subject">subject: <em>{c.subject}</em></span>
                  <button className="verify-btn" title="Coming soon - manual verification flow (Phase 3)" disabled>Needs verification</button>
                </header>
                <p className="metaphor-sentence">"{c.sentence}"</p>
                <p className="metaphor-reason">{c.reason}</p>
              </li>
            ))}
          </ul>
          {result.data.candidates.length === 0 && (
            <div className="empty-state">No metaphor candidates found in this corpus.</div>
          )}
        </>
      )}
    </div>
  );
}


// ── v1.0.1: per-document statistics ──────────────────────────────────────

function DocumentStatsPanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["document-stats", cid],
    queryFn: () => api.documentStats(cid),
  });
  const exportStatus = useExportStatus();

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!result.data) return;
    const headers = ["Document", "Language", "Tokens", "Types", "Sentences", "TTR", "Avg sentence length", "LIX", "RIX"];
    await exportWithFeedback(
      () => downloadTable(result.data.items.map((d) => [
        d.filename, d.language, d.tokens, d.types, d.sentences, d.ttr,
        d.avg_sentence_length, d.lix, d.rix,
      ]), headers, fmt as ExportFormat),
      `document_stats.${fmt}`,
      exportStatus.set,
    );
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <ExportButton onExport={onExport} disabled={!result.data?.items?.length} />
      </div>
      {exportStatus.el}
      {result.data && (result.data.items.length === 0 ? (
        <div className="empty-state">No documents with tokens yet.</div>
      ) : (
        <DataTable
          headers={["Document", "Lang", "Tokens", "Types", "Sentences", "TTR", "Avg SL", "LIX", "RIX"]}
          rows={result.data.items.map((d) => [
            d.filename, d.language || "?", d.tokens, d.types, d.sentences,
            d.ttr, d.avg_sentence_length, d.lix, d.rix,
          ])}
        />
      ))}
      <div className="hint" style={{ marginTop: "var(--space-2)" }}>
        LIX/RIX are language-neutral readability indices (long words &gt; 6 chars).
        TTR per document is sample-size-sensitive — compare documents of similar length.
      </div>
    </div>
  );
}

async function downloadTable(rows: (string | number)[][], headers: string[], _fmt: string): Promise<Blob> {
  // CSV serialization (client-side; the table is small — one row per document)
  void _fmt;
  const esc = (v: string | number) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [headers.map(esc).join(",")];
  for (const r of rows) lines.push(r.map(esc).join(","));
  return new Blob([lines.join("\n")], { type: "text/csv" });
}

// ── v1.0.1: corpus readability ───────────────────────────────────────────

function ReadabilityPanelView({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["readability", cid],
    queryFn: () => api.readability(cid),
  });
  const exportStatus = useExportStatus();

  const onExport = async (_fmt: ExportFormat | "svg" | "png") => {
    if (!result.data) return;
    await exportWithFeedback(
      async () => {
        const rows = Object.entries(result.data!).map(([k, v]) => [k, String(v)]);
        const body = [["measure", "value"], ...rows].map((r) => r.join(",")).join("\n");
        return new Blob([body], { type: "text/csv" });
      },
      `readability.csv`,
      exportStatus.set,
    );
  };

  const d = result.data;
  return (
    <div className="panel-content">
      <div className="toolbar">
        <ExportButton onExport={onExport} disabled={!d} />
      </div>
      {exportStatus.el}
      {d && (
        <>
          <div className="stat-row" style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap", margin: "var(--space-3) 0" }}>
            <Stat label="Flesch Reading Ease" value={d.flesch_reading_ease != null ? d.flesch_reading_ease.toFixed(1) : "—"}
                  hint="100 = very easy, 0 = very difficult (English only)" />
            <Stat label="Flesch–Kincaid grade" value={d.flesch_kincaid_grade != null ? d.flesch_kincaid_grade.toFixed(1) : "—"}
                  hint="U.S. school-grade level (English only)" />
            <Stat label="LIX" value={d.lix.toFixed(1)}
                  hint="< 30 very easy · 30–40 easy · 40–50 medium · 50–60 difficult · > 60 very difficult" />
            <Stat label="RIX" value={d.rix.toFixed(2)} hint="Long words per sentence (language-neutral)" />
          </div>
          <div className="result-meta">
            {d.words.toLocaleString()} words · {d.sentences.toLocaleString()} sentences ·{" "}
            {d.long_words.toLocaleString()} long words (&gt; 6 chars) · ASL = {d.avg_sentence_length}
            {d.documents != null && <> · {d.documents} documents</>}
          </div>
          {d.note && <div className="grounding-notice">{d.note}</div>}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat-card" title={hint}>
      <div className="stat-value" style={{ fontSize: 28, fontWeight: 700, color: "var(--accent, #1b4d3e)" }}>{value}</div>
      <div className="stat-label" style={{ fontWeight: 600 }}>{label}</div>
      {hint && <div className="hint" style={{ maxWidth: 220 }}>{hint}</div>}
    </div>
  );
}

// ── v1.0.1: frequency pivot by metadata variable ─────────────────────────

function GroupFrequencyPanel({ cid }: { cid: string }) {
  const [metaField, setMetaField] = useState("genre");
  const [minFreq, setMinFreq] = useState(1);
  const [submitted, setSubmitted] = useState<{ f: string; mf: number } | null>(null);

  const result = useQuery({
    queryKey: ["group-frequency", cid, submitted],
    queryFn: () => api.groupFrequency(cid, submitted!.f, "word", submitted!.mf, 100),
    enabled: !!submitted,
  });
  const exportStatus = useExportStatus();

  const data = result.data;
  const groupNames = data?.groups.map((g) => g.name) ?? [];

  const onExport = async (_fmt: ExportFormat | "svg" | "png") => {
    if (!data) return;
    await exportWithFeedback(
      async () => {
        const headers = ["item", "total", ...groupNames.flatMap((g) => [`${g} freq`, `${g} per-million`])];
        const lines = [headers.join(",")];
        for (const row of data.rows) {
          const cells = [row.item, row.total];
          for (const g of groupNames) {
            const c = row.groups[g] ?? { freq: 0, per_million: 0 };
            cells.push(c.freq, c.per_million);
          }
          lines.push(cells.join(","));
        }
        return new Blob([lines.join("\n")], { type: "text/csv" });
      },
      `group_frequency_${metaField}.csv`,
      exportStatus.set,
    );
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label title="Document metadata field to group by (e.g. genre, year, register)">
          Metadata field
          <input type="text" value={metaField} onChange={(e) => setMetaField(e.target.value)} style={{ width: 120 }} />
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <button onClick={() => setSubmitted({ f: metaField.trim(), mf: minFreq })}
                disabled={!metaField.trim()}>Compare</button>
        <ExportButton onExport={onExport} disabled={!data} />
      </div>
      {exportStatus.el}

      {data && (
        <>
          <div className="result-meta">
            Groups by <code>{data.meta_field}</code>:{" "}
            {data.groups.map((g) => `${g.name} (${g.documents} docs, ${g.tokens.toLocaleString()} tokens)`).join(" · ")}
          </div>
          {data.rows.length === 0 ? (
            <div className="empty-state">No rows met the threshold.</div>
          ) : (
            <DataTable
              headers={["Item", "Total", ...groupNames.map((g) => `${g} / pm`)]}
              rows={data.rows.map((row) => [
                row.item, row.total,
                ...groupNames.map((g) => row.groups[g]?.per_million ?? 0),
              ])}
            />
          )}
          <div className="hint" style={{ marginTop: "var(--space-2)" }}>
            Columns show per-million frequencies in each metadata group —
            normalized so groups of different sizes are directly comparable.
            Documents without the field are grouped under "(uncategorised)".
          </div>
        </>
      )}
    </div>
  );
}


// =========================================================================
// v1.2.0 — Vector KWIC (semantic concordancing; Anthony 2025,
// Applied Corpus Linguistics 5(3):100164)
//
// Mode A: a keyword concordance (regex/case toggles omitted — the node word
// is re-ranked by embedding similarity). Mode B: whole-sentence semantic
// search when no node is given. The engine decides and reports `mode`.
// Requires a local embedding model (bge-m3 recommended); when it is missing
// the engine answers 409 with {error:"embedding_model_missing", model, ...}
// and we render a one-click `ollama pull` setup card with live progress.
// =========================================================================

/** Body of the engine's HTTP 409 (embedding_model_missing) response. */
interface VectorKwicSetup {
  error: string;
  model: string;
  hint?: string;
  note?: string;
  settings_url?: string;
}

function VectorKwicPanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  const [query, setQuery] = useState("");
  const [node, setNode] = useState("");
  const [window, setWindow] = useState(6);
  const [topK, setTopK] = useState(50);
  const [minSim, setMinSim] = useState(0);
  const [normalizeArabic, setNormalizeArabic] = useState(false);

  const exportStatus = useExportStatus();

  // 409 setup-card state: the missing model + pull progress + "re-run" state.
  const [setup, setSetup] = useState<VectorKwicSetup | null>(null);
  const [pulledModel, setPulledModel] = useState<string | null>(null);
  const [pullState, setPullState] = useState<{ pct: number; status: string } | null>(null);
  const pullIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // v1.2.4: embedding model choice (bge-m3 default; nomic-embed-text for fast
  // English-only loads) + in-app warm-up (load model into memory, no terminal).
  const [embedModel, setEmbedModel] = useState("bge-m3");
  const [warm, setWarm] = useState<{ status: string; seconds?: number } | null>(null);
  const [warmError, setWarmError] = useState<string | null>(null);
  const warmIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // v1.2.4: 503 embedding_timeout → friendly card with a Warm-up button
  // (previously the raw HTTP 503 JSON leaked into the error line).
  const [timeoutInfo, setTimeoutInfo] = useState<{ model: string; hint?: string } | null>(null);
  // v1.2.5: 502 embedding_unreachable → Ollama dropped/refused the connection
  // (crashed / restarted / down). The model IS installed — no pull card here,
  // just the restart hint and a re-run button.
  const [unreachInfo, setUnreachInfo] = useState<{ model: string; hint?: string } | null>(null);

  const changeEmbedModel = (m: string) => {
    setEmbedModel(m);
    setSetup(null);
    setPulledModel(null);
    setTimeoutInfo(null);
    setUnreachInfo(null);
    setWarm(null);
    setWarmError(null);
    if (warmIntervalRef.current) clearInterval(warmIntervalRef.current);
    if (pullIntervalRef.current) clearInterval(pullIntervalRef.current);
  };

  const startWarmup = async (model: string) => {
    if (warmIntervalRef.current) clearInterval(warmIntervalRef.current);
    setWarmError(null);
    setWarm({ status: "warming" });
    try {
      await api.ollamaWarmup(model);
      const poll = setInterval(async () => {
        try {
          const s = await api.ollamaWarmupStatus(model);
          setWarm({ status: s.status, seconds: s.seconds });
          if (s.status === "warm" || s.status === "error") {
            clearInterval(poll);
            warmIntervalRef.current = null;
            if (s.status === "error") setWarmError(s.error || "unknown error");
          }
        } catch {
          clearInterval(poll);
          warmIntervalRef.current = null;
          setWarm(null);
          setWarmError("status poll failed");
        }
      }, 2000);
      warmIntervalRef.current = poll;
    } catch (e) {
      setWarm(null);
      setWarmError(e instanceof Error ? e.message : String(e));
    }
  };

  // Never leak an in-flight pull poll past unmount (same guard as SettingsView).
  useEffect(() => () => {
    if (pullIntervalRef.current) clearInterval(pullIntervalRef.current);
    if (warmIntervalRef.current) clearInterval(warmIntervalRef.current);
  }, []);

  const runMutation = useMutation({
    mutationFn: () =>
      api.vectorKwic(cid, {
        query: query.trim(),
        ...(node.trim() ? { node: node.trim() } : {}),
        level: "word",
        window,
        top_k: topK,
        min_similarity: minSim,
        normalize_arabic: normalizeArabic,
        model: embedModel,
      }),
    onSuccess: () => {
      setSetup(null);
      setTimeoutInfo(null);
      setUnreachInfo(null);
    },
    onError: (e: Error) => {
      if (e.message.startsWith("HTTP 409:")) {
        try {
          const detail = JSON.parse(e.message.slice("HTTP 409:".length)) as VectorKwicSetup;
          if (detail?.error === "embedding_model_missing") {
            setSetup(detail);
            setPulledModel(null);
          }
        } catch {
          // Malformed 409 body — fall through to the generic error display.
        }
      } else if (e.message.startsWith("HTTP 503:")) {
        // v1.2.4: cold-load timeout → actionable warm-up card instead of raw JSON.
        try {
          const detail = JSON.parse(e.message.slice("HTTP 503:".length)) as VectorKwicSetup & {
            error: string;
          };
          if (detail?.error === "embedding_timeout") {
            setTimeoutInfo({ model: detail.model, hint: detail.hint });
          }
        } catch {
          // Malformed 503 body — fall through to the generic error display.
        }
      } else if (e.message.startsWith("HTTP 502:")) {
        // v1.2.5: Ollama dropped/refused the connection — the model is
        // installed, so no 409/pull card; show the restart hint instead.
        try {
          const detail = JSON.parse(e.message.slice("HTTP 502:".length)) as VectorKwicSetup & {
            error: string;
          };
          if (detail?.error === "embedding_unreachable") {
            setUnreachInfo({ model: detail.model, hint: detail.hint });
          }
        } catch {
          // Malformed 502 body — fall through to the generic error display.
        }
      }
    },
  });

  const pullSetupModel = async () => {
    if (!setup?.model) return;
    const model = setup.model;
    // Overlapping pulls stop the previous poll (Issue 21.3 pattern).
    if (pullIntervalRef.current) clearInterval(pullIntervalRef.current);
    setPullState({ pct: 0, status: "starting" });
    try {
      await api.ollamaPull(model);
      const poll = setInterval(async () => {
        try {
          const status = await api.ollamaPullStatus(model);
          const pct = status.total > 0 ? Math.round((status.completed / status.total) * 100) : 0;
          setPullState({ pct, status: status.status });
          if (status.status === "success" || status.status === "error") {
            clearInterval(poll);
            pullIntervalRef.current = null;
            if (status.status === "success") {
              setPulledModel(model); // → "re-run" state on the setup card
            }
            setPullState(null);
          }
        } catch {
          clearInterval(poll);
          pullIntervalRef.current = null;
          setPullState(null);
        }
      }, 2000);
      pullIntervalRef.current = poll;
    } catch {
      setPullState(null);
    }
  };

  const data = runMutation.data;

  // Defensive guard (same pattern as the other panels); AnalysisView normally
  // blocks this panel until a corpus is active.
  if (!cid) return <div className="empty-state">{t(lang, "vk_need_corpus")}</div>;

  return (
    <div className="panel-content">
      <div className="vector-kwic-header">
        <h3>{t(lang, "vk_title")}</h3>
        <p className="hint">{t(lang, "vk_sub")}</p>
      </div>

      <div className="toolbar">
        <label style={{ flex: 2, minWidth: 240 }}>
          {t(lang, "vk_query")}
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && query.trim() && runMutation.mutate()}
            placeholder={t(lang, "vk_query_ph")}
          />
        </label>
        <label style={{ flex: 1, minWidth: 160 }}>
          {t(lang, "vk_node")}
          <input
            type="text"
            value={node}
            onChange={(e) => setNode(e.target.value)}
            placeholder={t(lang, "vk_node_ph")}
          />
        </label>
        <label>
          {t(lang, "vk_window")}
          <input type="number" min={1} max={20} value={window}
                 onChange={(e) => setWindow(Number(e.target.value))} />
        </label>
        <label style={{ flex: 1, minWidth: 200 }}>
          {t(lang, "vk_model_select")}
          <select value={embedModel} onChange={(e) => changeEmbedModel(e.target.value)}>
            <option value="bge-m3">{t(lang, "vk_model_bge")}</option>
            <option value="nomic-embed-text">{t(lang, "vk_model_nomic")}</option>
          </select>
        </label>
        <label>
          {t(lang, "vk_topk")}
          <input type="number" min={1} value={topK}
                 onChange={(e) => setTopK(Number(e.target.value))} />
        </label>
        <label>
          {t(lang, "vk_minsim")}
          <input type="number" min={0} max={1} step={0.05} value={minSim}
                 onChange={(e) => setMinSim(Number(e.target.value))} />
        </label>
        <label title={t(lang, "arb_normalize_hint")}>
          <input type="checkbox" checked={normalizeArabic}
                 onChange={(e) => setNormalizeArabic(e.target.checked)} />
          {t(lang, "vk_arabic_normalize")}
        </label>
        <button onClick={() => runMutation.mutate()} disabled={!query.trim() || runMutation.isPending}>
          {runMutation.isPending ? t(lang, "vk_running") : t(lang, "vk_run")}
        </button>
        <button className="btn-small" title={t(lang, "vk_warmup_hint")}
                onClick={() => startWarmup(embedModel)}
                disabled={warm?.status === "warming" || runMutation.isPending}>
          {t(lang, "vk_warmup")}
        </button>
        <ExportButton
          onExport={(fmt) => { if (data) downloadJsonResult(data, `vector_kwic.${fmt}`, exportStatus.set); }}
          disabled={!data}
        />
      </div>
      {exportStatus.el}

      {/* v1.2.4: warm-up state (loading the model into memory, no terminal) */}
      {warm?.status === "warming" && <div className="empty-state">{t(lang, "vk_warming")}</div>}
      {warm?.status === "warm" && (
        <div className="result-meta">
          {"\u2713"} {t(lang, "vk_warm_done")}
          {typeof warm.seconds === "number" ? ` (${warm.seconds}s)` : ""}
        </div>
      )}
      {warmError && <div className="error">{t(lang, "vk_warm_fail")}: {warmError}</div>}

      {/* 503 → warm-up card (cold model load, v1.2.4) */}
      {timeoutInfo && (
        <div className="vector-kwic-setup" role="status">
          <strong>{t(lang, "vk_timeout_card")}</strong>
          {timeoutInfo.hint && <div className="hint">{timeoutInfo.hint}</div>}
          <div className="hint">{t(lang, "vk_timeout_switch")}</div>
          <div className="vector-kwic-setup-row">
            <button className="btn-small" onClick={() => startWarmup(timeoutInfo.model)}
                    disabled={warm?.status === "warming"}>
              {warm?.status === "warming" ? t(lang, "vk_warming") : t(lang, "vk_warmup")}
            </button>
          </div>
        </div>
      )}

      {/* 502 → Ollama-unreachable card (dropped/refused connection, v1.2.5) */}
      {unreachInfo && (
        <div className="vector-kwic-setup" role="status">
          <strong>{t(lang, "vk_unreach_card")}</strong>
          {unreachInfo.hint && <div className="hint">{unreachInfo.hint}</div>}
          <div className="hint">{t(lang, "vk_unreach_retry")}</div>
          <div className="vector-kwic-setup-row">
            <button className="btn-small" onClick={() => runMutation.mutate()}
                    disabled={runMutation.isPending}>
              {runMutation.isPending ? t(lang, "vk_running") : t(lang, "vk_run")}
            </button>
          </div>
        </div>
      )}

      {/* 409 → one-click embedding-model setup card */}
      {setup && (
        <div className="vector-kwic-setup" role="status">
          <strong>{t(lang, "vk_setup_hint")}</strong>{" "}
          <code>{setup.model}</code>
          {setup.hint && <div className="hint">{setup.hint}</div>}
          {setup.note && <div className="hint">{t(lang, "vk_note")}: {setup.note}</div>}
          {pulledModel === setup.model ? (
            <div className="vector-kwic-setup-row">
              <span className="ollama-ready-text">{"\u2713"} {setup.model}</span>
              <button className="btn-small" onClick={() => runMutation.mutate()}
                      disabled={runMutation.isPending}>
                {runMutation.isPending ? t(lang, "vk_running") : t(lang, "vk_run")}
              </button>
            </div>
          ) : pullState ? (
            <div className="ollama-pull-progress">
              <div className="ollama-progress-bar" style={{ width: `${pullState.pct}%` }} />
              <span className="ollama-progress-text">
                {t(lang, "vk_setup_pulling").replace("{m}", setup.model)}
                {pullState.status !== "starting" ? ` ${pullState.pct}%` : ""}
              </span>
            </div>
          ) : (
            <div className="vector-kwic-setup-row">
              <button className="btn-small" onClick={pullSetupModel}>
                {t(lang, "vk_setup_run").replace("{m}", setup.model)}
              </button>
            </div>
          )}
        </div>
      )}

      {runMutation.isPending && <div className="empty-state">{t(lang, "vk_running")}</div>}
      {runMutation.isError && !setup && (
        <div className="error">Error: {String(runMutation.error)}</div>
      )}

      {data && (
        <>
          <div className="result-meta">
            <span className="pos-tag pos-other">
              {data.mode === "semantic" ? t(lang, "vk_mode_semantic") : t(lang, "vk_mode_keyword")}
            </span>
            {" "}{t(lang, "vk_model").replace("{m}", data.model)}
            {" · "}{t(lang, "vk_scanned").replace("{n}", String(data.scanned))}
            {data.note ? <span className="hint"> — {data.note}</span> : null}
          </div>

          {data.lines.length === 0 ? (
            <div className="empty-state">{t(lang, "vk_no_lines")}</div>
          ) : (
            <table className="kwic-table">
              <thead>
                <tr>
                  <th>Line ID</th>
                  <th>Document</th>
                  <th className="right-align">Left context</th>
                  <th>Node</th>
                  <th>Right context</th>
                  <th>{t(lang, "vk_similarity")}</th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((l) => (
                  <tr key={l.line_id}>
                    <td className="line-id" title={l.line_id}>{l.line_id.slice(-12)}</td>
                    <td className="doc" title={l.document_filename}>{l.document_filename}</td>
                    <td className="left">{l.left}</td>
                    <td className="node">{l.node}</td>
                    <td className="right">{l.right}</td>
                    <td className="similarity" title="Raw cosine similarity">{l.similarity.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
