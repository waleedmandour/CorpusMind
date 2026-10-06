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

import { api, exportWithFeedback, type ExportFormat, type ReferenceCorpusEntry, type POSAnalysisResult, type SemanticAnalysisResult, type DiscourseCategory, type SentenceTreeToken, type DepConcordanceRow } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI, type NavTarget } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";
import { ExportButton } from "@/components/ExportButton";
import { CollocationNetwork } from "@/components/CollocationNetwork";
import { SlowQueryNote } from "@/components/SlowQueryNote";
import { PersuasionRadar } from "@/components/PersuasionRadar";
import { DiscourseBarChart } from "@/components/DiscourseBarChart";
import { ChartCsvExportButton } from "@/components/ChartExportButtons";
import { TaxonomyRadar, RADAR_MIN_AXES, RADAR_MAX_AXES } from "@/components/TaxonomyRadar";

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
// v1.2.3 - Analysis tool CARDS (replace the flat text tab strip).
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
  // Corpus-level metrics - this shell only (no sidebar entry), kept last.
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
            rows={result.data.rows.map((r) => [r.item, r.freq, r.per_million, r.percent, r.range, r.range_percent ?? "-"])}
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
      {/* v1.2.10: queued-under-load feedback instead of a silent spinner —
          the soak showed ~40 s waits at full classroom width. */}
      <SlowQueryNote pending={result.isPending} lang={lang} />
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
                  ...measureKeys.map((k) => (r as any)[k] ?? "-"),
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
              // v1.2.9: comparison palette — green = over-represented in target.
              <span key="lr" className="keyness-effect keyness-effect-pos">{fmt(r.log_ratio)}</span>,
              <span key="pd" className="keyness-effect keyness-effect-pos">{fmt(r.pct_diff)}</span>,
              fmt(r.simple_maths), fmt(r.odds_ratio),
            ])}
          />
          <h3>Negative keywords (under-represented in target)</h3>
          <DataTable
            headers={["Term", "f1", "f2", "LL", "χ²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio"]}
            rows={(result.data as any).negative_keywords.map((r: any) => [
              r.term, r.f1, r.f2, fmt(r.log_likelihood), fmt(r.chi_square),
              // v1.2.9: red = under-represented in target (reference over-use).
              <span key="lr" className="keyness-effect keyness-effect-neg">{fmt(r.log_ratio)}</span>,
              <span key="pd" className="keyness-effect keyness-effect-neg">{fmt(r.pct_diff)}</span>,
              fmt(r.simple_maths), fmt(r.odds_ratio),
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
              Gries' DP: 0 = perfectly even, 1 = concentrated - expected proportions are weighted by document size (v1.0.1).
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
  if (v === null || v === undefined) return "-";
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
// v1.2.11: ur/hi/fa - UPOS only (no PTB/CLAWS tagger exists for them, and
// the USAS lexicons are en/ar only).
const TAGSETS_NEW_LANGS = ["upos"];

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
  const tagsetOptions = language === "ar"
    ? TAGSETS_AR
    : ["ur", "hi", "fa"].includes(language)
      ? TAGSETS_NEW_LANGS
      : TAGSETS_EN;

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
            approximation - cite the USAS taxonomy in publications.
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
  const lang = useUI((s) => s.lang);
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

      {result.isError && (
        <div className="lens-error-card" role="alert">
          <strong>{t(lang, "grammar_error_title")}</strong>
          <p>{String(result.error)}</p>
        </div>
      )}

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


// v1.2.8 (review #2): fixed part-of-speech palette for the dependency
// concordance table, following the displaCy convention of colour-coding
// POS with a fixed legend. Values are tuned for contrast on both the light
// and dark theme backgrounds; the legend under the table maps every color
// back to its tag, so the coding never depends on memory.
const DEP_POS_COLORS: Record<string, string> = {
  NOUN: "#4a90d9",
  PROPN: "#7c5cd6",
  VERB: "#2e9e5b",
  AUX: "#8a8f98",
  ADJ: "#d9862c",
  ADV: "#c2578e",
  PRON: "#b04a5a",
  DET: "#6b7f9e",
  ADP: "#a0793d",
  NUM: "#3aa0a8",
  CCONJ: "#9462bd",
  SCONJ: "#7d8bc0",
  PART: "#8b8147",
  INTJ: "#c2703e",
  PUNCT: "#8a8f98",
  X: "#8a8f98",
};
const DEP_POS_LEGEND_ORDER = [
  "NOUN", "PROPN", "VERB", "AUX", "ADJ", "ADV", "PRON", "DET",
  "ADP", "NUM", "CCONJ", "SCONJ", "PART", "INTJ", "X",
];

function PosChip({ pos }: { pos: string }) {
  const tag = (pos || "X").toUpperCase();
  const color = DEP_POS_COLORS[tag] ?? DEP_POS_COLORS.X;
  return (
    <span className="pos-chip" style={{ color, borderColor: color }}>
      {tag}
    </span>
  );
}

// v1.2.7 (§2): displaCy-style arc diagram (in-house SVG, offline-safe -
// no external renderer dependency). Tokens sit on a baseline; every
// non-root dependency is an arc from head to dependent with the relation
// label on its apex. Arc height scales with head-dependent distance.
function DependencyTreeSVG({ tokens }: { tokens: SentenceTreeToken[] }) {
  if (tokens.length === 0) return null;
  const CHAR_W = 7.2;
  const PAD = 14;
  const ARC_BASE = 46; // baseline → lowest arc apex
  const ARC_STEP = 16; // extra height per span unit
  const H = ARC_BASE + Math.max(1, tokens.length) * ARC_STEP + 8;

  // x centers per token
  const widths = tokens.map((t) => Math.max(28, t.text.length * CHAR_W + 10));
  const xs: number[] = [];
  let x = PAD;
  for (const w of widths) {
    xs.push(x + w / 2);
    x += w;
  }
  const totalW = x + PAD;
  const baseline = H - 22;

  const arcs = tokens
    .filter((t) => t.head > 0)
    .map((t) => {
      const from = xs[t.head - 1] ?? 0;
      const to = xs[t.id - 1] ?? 0;
      const span = Math.abs(t.head - t.id);
      const lift = Math.min(ARC_BASE - 12, 12 + span * ARC_STEP);
      const apex = baseline - lift;
      const mx = (from + to) / 2;
      return { key: `${t.id}-${t.head}`, from, to, mx, apex, label: t.rel_base || t.rel, upward: t.head < t.id };
    });

  return (
    <div className="deptree-wrap">
      <svg viewBox={`0 0 ${totalW} ${H}`} width="100%" role="img" aria-label="dependency tree">
        {arcs.map((a) => (
          <g key={a.key}>
            <path
              d={`M ${a.from} ${baseline - 6} Q ${a.mx} ${a.apex - 26} ${a.to} ${baseline - 6}`}
              fill="none"
              stroke="var(--brand-500)"
              strokeWidth="1.4"
            />
            <polygon
              points={`${a.to - 3.5},${baseline - 9} ${a.to + 3.5},${baseline - 9} ${a.to},${baseline - 4}`}
              fill="var(--brand-500)"
            />
            <text x={a.mx} y={a.apex - 30} textAnchor="middle" className="deptree-label">
              {a.label}
            </text>
          </g>
        ))}
        <line x1={PAD / 2} y1={baseline} x2={totalW - PAD / 2} y2={baseline} stroke="var(--border-strong)" strokeWidth="1" />
        {tokens.map((t, i) => (
          <g key={t.id}>
            <text x={xs[i]} y={baseline + 15} textAnchor="middle" className="deptree-token">{t.text}</text>
            <text x={xs[i]} y={baseline + 27} textAnchor="middle" className="deptree-pos">{t.pos}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function DependencyPanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  const [relation, setRelation] = useState("nsubj");
  const [valencyLemma, setValencyLemma] = useState("");
  const [valencyQuery, setValencyQuery] = useState("");
  const result = useQuery({
    queryKey: ["dep", cid, relation],
    queryFn: () => api.dependencies(cid, relation, 100),
  });

  // v1.2.7 (§2): relation profile grouped by grammatical function
  const profile = useQuery({
    queryKey: ["ud-profile", cid],
    queryFn: () => api.udProfile(cid),
    staleTime: 5 * 60 * 1000,
  });

  // v1.2.7 (§2): valency frames for one lemma
  const valency = useQuery({
    queryKey: ["valency", cid, valencyQuery],
    queryFn: () => api.valency(cid, valencyQuery),
    enabled: valencyQuery.trim().length > 0,
  });

  // v1.2.8 (review #2): KWIC-style dependency concordance — one row per
  // hit (left | node | right | head | relation | source), replacing the
  // per-instance sentence dropdown. A relation filter is pre-applied so
  // the table shows content immediately; the node query narrows it.
  const [concNode, setConcNode] = useState("");
  const [concNodeApplied, setConcNodeApplied] = useState("");
  const [concRelation, setConcRelation] = useState("nsubj");
  const [concPos, setConcPos] = useState("");
  const [concSort, setConcSort] = useState<{ key: "source" | "node" | "relation" | "head"; dir: 1 | -1 } | null>(null);
  const conc = useQuery({
    queryKey: ["dep-conc", cid, concNodeApplied, concRelation, concPos],
    queryFn: () =>
      api.depConcordance(cid, {
        node_query: concNodeApplied,
        relation: concRelation || null,
        pos: concPos || null,
        window: 6,
        limit: 200,
      }),
  });

  // Selected row's sentence, rendered as the arc diagram below the table.
  const [selectedTree, setSelectedTree] = useState("");
  const [treeDoc, treeSent] = selectedTree ? selectedTree.split(/:(?=\d+$)/) : ["", "0"];
  const tree = useQuery({
    queryKey: ["tree", cid, treeDoc, treeSent],
    queryFn: () => api.sentenceTree(cid, treeDoc, Number(treeSent)),
    enabled: !!treeDoc,
  });

  const concRows: DepConcordanceRow[] = conc.data?.rows ?? [];
  const sortedRows = [...concRows];
  if (concSort) {
    const { key, dir } = concSort;
    sortedRows.sort((a, b) => {
      // "source" sorts on the filename column (the row field name differs).
      const va = String(key === "source" ? a.document_filename : a[key] ?? "");
      const vb = String(key === "source" ? b.document_filename : b[key] ?? "");
      return va.localeCompare(vb) * dir;
    });
  }
  const onConcSort = (key: "source" | "node" | "relation" | "head") => {
    setConcSort((prev) =>
      prev && prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: 1 },
    );
  };
  const concArrow = (key: "source" | "node" | "relation" | "head") =>
    concSort?.key === key ? (concSort.dir === 1 ? " ▲" : " ▼") : "";

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
        produced in 8.1 - not a separate pipeline. Relation labels are normalized onto the
        UD v2 universal inventory (37 relations) - spaCy ClearNLP labels like
        <code> dobj</code>/<code>ROOT</code> map onto <code>obj</code>/<code>root</code> at read time.
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

      {/* v1.2.7 (§2): UD v2 relation profile by functional group */}
      {profile.data && profile.data.total_relations > 0 && (
        <>
          <h3>UD relation profile (37 universal relations)</h3>
          <DataTable
            headers={["Functional group", "Frequency", "% of relations"]}
            rows={profile.data.groups.map((g) => [g.label, g.freq, g.percent])}
          />
          <details className="ud-profile-details">
            <summary>All relations</summary>
            <DataTable
              headers={["Relation", "Group", "Frequency", "Per million"]}
              rows={profile.data.relations.map((r) => [r.relation, r.group_label, r.freq, r.per_million])}
            />
          </details>
          <div className="grounding-notice"><em>{profile.data.citation}</em></div>
        </>
      )}

      {/* v1.2.7 (§2): valency frames */}
      <h3>Valency frames</h3>
      <div className="toolbar">
        <input
          type="text"
          value={valencyLemma}
          placeholder="verb lemma, e.g. give"
          onChange={(e) => setValencyLemma(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") setValencyQuery(valencyLemma.trim()); }}
        />
        <button type="button" onClick={() => setValencyQuery(valencyLemma.trim())} disabled={!valencyLemma.trim()}>
          Show frames
        </button>
      </div>
      {valency.data && (
        valency.data.total_occurrences > 0 ? (
          <>
            <div className="result-meta">
              <strong>{valency.data.lemma}</strong> · {valency.data.total_occurrences.toLocaleString()} clause-head occurrences
            </div>
            <DataTable
              headers={["Frame", "Frequency", "%", "Examples"]}
              rows={valency.data.frames.map((f) => [f.frame, f.freq, f.percent, f.examples.join(" · ")])}
            />
            {valency.data.obliques.length > 0 && (
              <DataTable
                headers={["Oblique preposition", "Frequency"]}
                rows={valency.data.obliques.map((o) => [o.prep, o.freq])}
              />
            )}
          </>
        ) : (
          <div className="result-meta">No clause-head occurrences of <code>{valency.data.lemma}</code>.</div>
        )
      )}

      {/* v1.2.8 (review #2): dependency concordance — one row per hit */}
      <h3>{t(lang, "dep_conc_title")}</h3>
      <div className="grounding-notice">
        {t(lang, "dep_conc_intro")}
      </div>
      <div className="toolbar">
        <label htmlFor="dep-conc-node">{t(lang, "dep_conc_node")}</label>
        <input
          id="dep-conc-node"
          type="text"
          value={concNode}
          placeholder={t(lang, "dep_conc_node_hint")}
          onChange={(e) => setConcNode(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") setConcNodeApplied(concNode.trim()); }}
        />
        <button
          type="button"
          onClick={() => setConcNodeApplied(concNode.trim())}
          disabled={!concNode.trim() && !concRelation && !concPos}
        >
          {t(lang, "dep_conc_search")}
        </button>
        <select
          aria-label={t(lang, "dep_conc_col_rel")}
          value={concRelation}
          onChange={(e) => setConcRelation(e.target.value)}
        >
          <option value="">{t(lang, "dep_conc_relation_all")}</option>
          <option value="nsubj">nsubj</option>
          <option value="obj">obj</option>
          <option value="iobj">iobj</option>
          <option value="obl">obl</option>
          <option value="amod">amod</option>
          <option value="compound">compound</option>
          <option value="conj">conj</option>
          <option value="advcl">advcl</option>
          <option value="ccomp">ccomp</option>
          <option value="xcomp">xcomp</option>
        </select>
        <select
          aria-label={t(lang, "dep_conc_col_node")}
          value={concPos}
          onChange={(e) => setConcPos(e.target.value)}
        >
          <option value="">{t(lang, "dep_conc_pos_all")}</option>
          {DEP_POS_LEGEND_ORDER.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <ExportButton
          onExport={(fmt_) => { if (conc.data) { downloadJsonResult(conc.data, `dep-concordance.${fmt_}`, exportStatus.set); } }}
          disabled={!conc.data}
        />
      </div>
      {conc.isError && (
        <div className="grounding-notice"><strong>⚠</strong> {String(conc.error)}</div>
      )}
      {conc.data && (
        <div className="result-meta">
          {t(lang, "dep_conc_total")
            .replace("{n}", conc.data.total.toLocaleString())
            .replace("{m}", String(conc.data.rows.length))}
        </div>
      )}
      {conc.data && conc.data.rows.length === 0 && (
        <div className="empty-state">{t(lang, "dep_conc_no_rows")}</div>
      )}
      {sortedRows.length > 0 && (
        <div className="dep-conc-table-wrap">
          <table className="dep-conc-table">
            <thead>
              <tr>
                <th className="num">{t(lang, "dep_conc_col_left")}</th>
                <th
                  className={clsx("sortable", concSort?.key === "node" && "sorted")}
                  onClick={() => onConcSort("node")}
                  aria-sort={concSort?.key === "node" ? (concSort.dir === 1 ? "ascending" : "descending") : undefined}
                >
                  {t(lang, "dep_conc_col_node")}{concArrow("node")}
                </th>
                <th className="num">{t(lang, "dep_conc_col_right")}</th>
                <th
                  className={clsx("sortable", concSort?.key === "head" && "sorted")}
                  onClick={() => onConcSort("head")}
                  aria-sort={concSort?.key === "head" ? (concSort.dir === 1 ? "ascending" : "descending") : undefined}
                >
                  {t(lang, "dep_conc_col_head")}{concArrow("head")}
                </th>
                <th
                  className={clsx("sortable", concSort?.key === "relation" && "sorted")}
                  onClick={() => onConcSort("relation")}
                  aria-sort={concSort?.key === "relation" ? (concSort.dir === 1 ? "ascending" : "descending") : undefined}
                >
                  {t(lang, "dep_conc_col_rel")}{concArrow("relation")}
                </th>
                <th
                  className={clsx("sortable", concSort?.key === "source" && "sorted")}
                  onClick={() => onConcSort("source")}
                  aria-sort={concSort?.key === "source" ? (concSort.dir === 1 ? "ascending" : "descending") : undefined}
                >
                  {t(lang, "dep_conc_col_source")}{concArrow("source")}
                </th>
                <th aria-label="tree" />
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r) => (
                <tr
                  key={r.evidence_id}
                  className={clsx(selectedTree === `${r.doc}:${r.sentence_idx}` && "selected")}
                >
                  <td className="num ctx">{r.left}</td>
                  <td className="node-cell">
                    <strong>{r.node}</strong> <PosChip pos={r.node_pos} />
                  </td>
                  <td className="num ctx">{r.right}</td>
                  <td>{r.head}{r.head_pos && <span className="cat-meta"> ({r.head_pos})</span>}</td>
                  <td><code className="dep-rel-label">{r.relation}</code></td>
                  <td className="source" title={r.evidence_id}>
                    {r.document_filename} · {t(lang, "dep_conc_sent_n").replace("{n}", String(r.sentence_idx + 1))}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-small"
                      onClick={() => setSelectedTree(`${r.doc}:${r.sentence_idx}`)}
                    >
                      {t(lang, "dep_conc_view_tree")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sortedRows.length > 0 && (
        <div className="dep-conc-legend" aria-label={t(lang, "dep_conc_legend")}>
          <span className="dep-conc-legend-title">{t(lang, "dep_conc_legend")}:</span>
          {DEP_POS_LEGEND_ORDER.map((p) => (
            <span key={p} className="pos-chip" style={{ color: DEP_POS_COLORS[p], borderColor: DEP_POS_COLORS[p] }}>
              {p}
            </span>
          ))}
        </div>
      )}
      {tree.data && tree.data.tokens.length > 0 && (
        <>
          <DependencyTreeSVG tokens={tree.data.tokens} />
          <div className="grounding-notice"><em>{tree.data.citation}</em></div>
        </>
      )}
    </div>
  );
}


// v1.2.7 (§3): sortable column keys for the discourse DataTable.
type DiscourseSortKey =
  | "category"
  | "freq"
  | "per_million"
  | "dp"
  | "log_likelihood"
  | "log_ratio"
  | "pct_diff"
  | "simple_maths";

// Named fmtNum to stay clear of the 4-decimal fmt() helper used by the
// dispersion panel; the discourse table wants short per-column precision.
const fmtNum = (v: number | null | undefined, digits: number) =>
  v == null ? "-" : v.toLocaleString(undefined, { maximumFractionDigits: digits });

function DiscoursePanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  // v1.2.6: multi-taxonomy support - the lens is user-selectable and each
  // result names + cites its taxonomy. Default stays Hyland 2005.
  const [taxonomy, setTaxonomy] = useState("hyland2005");
  // v1.2.7 (§3): optional comparison corpus → per-category keyness battery.
  const [compareId, setCompareId] = useState("");
  const [sortKey, setSortKey] = useState<DiscourseSortKey>("freq");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const result = useQuery({
    queryKey: ["discourse", cid, taxonomy, compareId],
    queryFn: () => api.discourse(cid, taxonomy, compareId || null),
  });
  // v1.2.8 (review #1): the 503s (missing package / lexicon) used to be
  // invisible in this panel — only the status-bar counter showed them.
  // Surface the error inline and, for the persuasion lens, the resource
  // health payload (doctor status) instead of a blanket failure.
  const piHealth = useQuery({
    queryKey: ["pi-health"],
    queryFn: () => api.persuasionHealth(),
    enabled: taxonomy === "persuasion_gong2026",
    staleTime: 60 * 1000,
  });
  const httpError = (() => {
    if (!result.isError) return null;
    const raw = String(result.error ?? "");
    const m = raw.match(/^HTTP (\d+): ([\s\S]*)$/);
    const status = m ? Number(m[1]) : 0;
    let detail = m ? m[2] : raw;
    try {
      const parsed = JSON.parse(detail);
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* body was not JSON — show the raw message */
    }
    return { status, detail };
  })();
  const taxonomies = useQuery({
    queryKey: ["discourse-taxonomies", cid],
    queryFn: () => api.discourseTaxonomies(cid),
    staleTime: 5 * 60 * 1000,
  });
  // v1.2.7 (§3): sibling corpora as comparison candidates.
  const corpusMeta = useQuery({
    queryKey: ["corpus", cid],
    queryFn: () => api.getCorpus(cid),
    staleTime: 5 * 60 * 1000,
  });
  const projectId = corpusMeta.data?.project_id;
  const siblings = useQuery({
    queryKey: ["corpora", projectId],
    queryFn: () => api.listCorpora(projectId as string),
    enabled: !!projectId,
    staleTime: 5 * 60 * 1000,
  });
  const compareOptions = (siblings.data ?? []).filter((c) => c.id !== cid);
  const compareName = compareOptions.find((c) => c.id === compareId)?.name;
  const exportStatus = useExportStatus();

  const opts: Array<{ key: string; name: string }> =
    taxonomies.data?.taxonomies.map((tx) => ({ key: tx.key, name: tx.name })) ?? [
      { key: "hyland2005", name: "Hyland 2005" },
      { key: "hallidayhasan1976", name: "Halliday & Hasan 1976" },
      { key: "martinwhite2005", name: "Martin & White 2005" },
      { key: "cialdini2007", name: "Cialdini 2007" },
      { key: "usas", name: "CLAWS/USAS semantic tagset (top-level)" },
      { key: "sfg_hm2014", name: "SFG Transitivity & Modality (Halliday & Matthiessen 2014)" },
      { key: "persuasion_gong2026", name: "Persuasion Index (Wang & Gong 2026) - 15 dimensions" },
    ];
  // v1.2.10: language-coverage badge — driven entirely by the engine
  // registry via /discourse/taxonomies (traceable, not hardcoded here).
  const txInfo = taxonomies.data?.taxonomies.find((tx) => tx.key === taxonomy);
  const isUsas = result.data?.taxonomy_key === "usas";
  const isPersuasion = result.data?.taxonomy_key === "persuasion_gong2026";

  // v1.2.7 (§3): rows + sorting. Frequencies default to descending; a
  // second click on the active header flips the direction. Null measures
  // (Log Ratio/%DIFF undefined on an absent side) always sort last.
  const rows = Object.entries(result.data?.categories ?? {}).map(([cat, info]) => ({ cat, info }));
  const sortVal = (r: { cat: string; info: DiscourseCategory }): number | string => {
    switch (sortKey) {
      case "category": return r.cat;
      case "freq": return r.info.freq;
      case "per_million": return r.info.per_million ?? Number.NEGATIVE_INFINITY;
      case "dp": return r.info.dp ?? 0;
      case "log_likelihood": return r.info.log_likelihood ?? Number.NEGATIVE_INFINITY;
      case "log_ratio": return r.info.log_ratio ?? Number.NEGATIVE_INFINITY;
      case "pct_diff": return r.info.pct_diff ?? Number.NEGATIVE_INFINITY;
      case "simple_maths": return r.info.simple_maths ?? Number.NEGATIVE_INFINITY;
    }
  };
  rows.sort((a, b) => {
    const va = sortVal(a);
    const vb = sortVal(b);
    const cmp =
      typeof va === "string" || typeof vb === "string"
        ? String(va).localeCompare(String(vb))
        : (va as number) - (vb as number);
    return cmp * sortDir;
  });
  const onSort = (key: DiscourseSortKey) => {
    if (key === sortKey) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(key === "category" ? 1 : -1);
    }
  };
  const arrow = (key: DiscourseSortKey) => (key === sortKey ? (sortDir === 1 ? " ▲" : " ▼") : "");
  const hasCompare = !!result.data?.compare_corpus_id;
  const anyCochran = rows.some((r) => r.info.cochran_warning);

  const columns: Array<{ key: DiscourseSortKey; labelKey: TranslationKey; titleKey?: TranslationKey; numeric: boolean }> = [
    { key: "category", labelKey: "discourse_col_category", numeric: false },
    { key: "freq", labelKey: "discourse_col_freq", numeric: true },
    { key: "per_million", labelKey: "discourse_col_pm", numeric: true },
    { key: "dp", labelKey: "discourse_col_dp", titleKey: "discourse_dp_hint", numeric: true },
    { key: "log_likelihood", labelKey: "discourse_col_ll", titleKey: "discourse_ll_hint", numeric: true },
    { key: "log_ratio", labelKey: "discourse_col_lr", titleKey: "discourse_lr_hint", numeric: true },
    { key: "pct_diff", labelKey: "discourse_col_pd", numeric: true },
    { key: "simple_maths", labelKey: "discourse_col_sm", numeric: true },
    { key: "category", labelKey: "discourse_col_examples", numeric: false },
  ];

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
        {compareOptions.length > 0 && (
          <>
            <label htmlFor="discourse-compare" style={{ fontWeight: 600 }}>
              {t(lang, "discourse_compare")}:{" "}
            </label>
            <select
              id="discourse-compare"
              value={compareId}
              onChange={(e) => setCompareId(e.target.value)}
            >
              <option value="">{t(lang, "discourse_compare_none")}</option>
              {compareOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </>
        )}
        <ExportButton onExport={(fmt_) => { if (result.data) { downloadJsonResult(result.data, `discourse.${fmt_}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      {/* v1.2.10: language-coverage badge — traceable to the registry (the
          engines declares which languages each lens's cue sets/lexicons
          actually support); hidden until the taxonomies query resolves. */}
      {txInfo?.languages && txInfo.languages.length > 0 && (
        <div className="lang-coverage-note">
          {t(lang, "lang_coverage")}:{" "}
          {txInfo.languages.map((l) => (
            <span key={l} className="lang-chip">{l}</span>
          ))}
        </div>
      )}
      <div className="grounding-notice">
        <strong>Note:</strong> {t(lang, "discourse_note_intro")}{" "}
        {result.data?.citation && <em>{result.data.citation}</em>}
      </div>
      {hasCompare && (
        <div className="grounding-notice">
          {t(lang, "discourse_compare_hint")}{" "}
          {compareName && <em>{compareName}</em>}
          {result.data?.compare_total_tokens != null && (
            <> · N = {result.data.compare_total_tokens.toLocaleString()}</>
          )}
        </div>
      )}
      {isPersuasion && (
        <div className="grounding-notice pi-disclaimer">
          <strong>⚠</strong> {t(lang, "pi_disclaimer")}
        </div>
      )}

      {/* v1.2.8 (review #1): engine errors are now visible in the panel */}
      {httpError && (
        <div className="lens-error-card" role="alert">
          <strong>{t(lang, "discourse_error_title")}</strong>
          {httpError.status > 0 && <span className="lens-error-status"> HTTP {httpError.status}</span>}
          <p>{httpError.detail}</p>
          <button type="button" className="btn-small" onClick={() => result.refetch()}>
            {t(lang, "discourse_error_retry")}
          </button>
        </div>
      )}

      {/* v1.2.8 (review #1): persuasion resource health — what is active vs
          degraded to neutral baselines, so the fallback choice is explicit */}
      {taxonomy === "persuasion_gong2026" && piHealth.data && (
        <div className="pi-health-card">
          <div className="pi-health-head">
            <strong>{t(lang, "pi_health_title")}</strong>
            {piHealth.data.installed ? (
              <span className="pi-health-badge ok">
                {t(lang, "pi_health_installed")} {piHealth.data.version}
              </span>
            ) : (
              <span className="pi-health-badge warn">{t(lang, "pi_health_not_installed")}</span>
            )}
          </div>
          <p className="cat-meta">{piHealth.data.policy}</p>
          {piHealth.data.installed && !piHealth.data.complete && (
            <p className="cat-meta">
              {t(lang, "pi_health_missing_n").replace("{n}", String(piHealth.data.missing.length))}
            </p>
          )}
          {piHealth.data.installed && piHealth.data.complete && (
            <p className="cat-meta">{t(lang, "pi_health_complete")}</p>
          )}
          {piHealth.data.installed && (
            <ul className="pi-health-resources">
              {Object.entries(piHealth.data.resources).map(([name, res]) => {
                // v1.2.9: per-resource install guidance for the license-
                // restricted files (never bundled — see install_hints).
                const hint = piHealth.data.install_hints?.[name];
                return (
                <li key={name}>
                  <span className={clsx("pi-health-badge", res.available ? "ok" : "warn")}>
                    {res.available ? "✓" : "○"} {name}
                  </span>
                  {!res.available && (
                    <details className="pi-health-resource-detail">
                      <summary>
                        {t(lang, "pi_health_features")}
                        {res.features?.length ? ` (${res.features.length})` : ""}
                      </summary>
                      <p>{res.detail}</p>
                      {res.features?.length ? <p>{res.features.join(" · ")}</p> : null}
                      {res.license_note ? <p className="cat-meta">{res.license_note}</p> : null}
                      {hint && (
                        <div className="pi-health-install-hint">
                          <p>
                            <strong>{t(lang, "pi_health_install_title")}</strong>{" "}
                            {t(lang, "pi_health_install_body")}
                          </p>
                          <ol>
                            <li>
                              {t(lang, "pi_health_install_source")}:{" "}
                              <a href={hint.source_url} target="_blank" rel="noreferrer">
                                {hint.source_url}
                              </a>
                            </li>
                            <li>
                              {t(lang, "pi_health_install_where")}{" "}
                              <code>{hint.folder}/{hint.filename}</code>
                              <button
                                type="button"
                                className="pi-health-copy-btn"
                                onClick={() => {
                                  void navigator.clipboard?.writeText(`${hint.folder}/${hint.filename}`);
                                }}
                                title={t(lang, "pi_health_copy")}
                              >
                                ⧉
                              </button>
                            </li>
                            <li>{t(lang, "pi_health_install_restart")}</li>
                          </ol>
                          <p className="cat-meta">
                            {t(lang, "pi_health_install_env")} <code>{hint.engine_setting}</code>
                          </p>
                        </div>
                      )}
                    </details>
                  )}
                </li>
                );
              })}
            </ul>
          )}
          {!piHealth.data.installed && piHealth.data.install_hint && (
            <p><code>{piHealth.data.install_hint}</code></p>
          )}
        </div>
      )}

      {result.data && (
        <>
          <div className="result-meta">
            Taxonomy: <strong>{result.data.taxonomy}</strong> ·
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens
            {isUsas && result.data.unmatched_percent != null && (
              <> · <span title={t(lang, "discourse_unmatched_hint")}>{t(lang, "discourse_unmatched")}: <strong>{result.data.unmatched_percent}%</strong></span></>
            )}
            {isPersuasion && result.data.scored_documents != null && (
              <> · {t(lang, "pi_scored_docs")}: <strong>{result.data.scored_documents}</strong></>
            )}
          </div>
          {/* v1.2.8 (review #3): chart matching the table below - the same
              rows, the same sort. The persuasion lens keeps its radar. */}
          {!isPersuasion && rows.length > 0 && (
            <DiscourseBarChart rows={rows.slice(0, 25)} hasCompare={hasCompare} />
          )}
          {/* v1.2.10: generic profile radar for cue lenses with 3-12
              categories (Cialdini 6, Hyland 10, Appraisal 7, SFG 10; the
              21-tag USAS stays on the bar chart). Axis length is normalized
              to the most frequent category — the hint line says so. */}
          {!isPersuasion && result.data && rows.length >= RADAR_MIN_AXES && rows.length <= RADAR_MAX_AXES && (
            <div className="taxonomy-radar-wrap">
              {/* key: force a clean re-render when the taxonomy changes so
                  axis labels can never linger from the previous lens. */}
              <TaxonomyRadar
                key={result.data.taxonomy_key}
                categories={result.data.categories}
                noHitsLabel={t(lang, "discourse_radar_no_hits")}
                exportName={`corpusmind-discourse-radar-${result.data.taxonomy_key ?? "lens"}`}
              />
              <div className="taxonomy-radar-hint"><em>{t(lang, "discourse_radar_hint")}</em></div>
            </div>
          )}
          {/* v1.2.10: generic cue co-occurrence — sentences matching cues
              from two categories. Co-occurrence is not causation; the hint
              says so in both UI languages. */}
          {!!result.data?.cooccurrence?.length && (
            <div className="coocc-card">
              <div className="coocc-head">
                <strong>{t(lang, "discourse_coocc_title")}</strong>
                {/* v1.2.10 field fixes: Export CSV — same rows as the table
                    (pair + shared-sentence count), RFC-4180 + UTF-8 BOM. */}
                <ChartCsvExportButton
                  headers={[
                    t(lang, "discourse_coocc_pair"),
                    t(lang, "discourse_coocc_sentences"),
                  ]}
                  rows={result.data.cooccurrence.map((p) => [
                    `${p.a.replace(/_/g, " ")} x ${p.b.replace(/_/g, " ")}`,
                    p.sentences,
                  ])}
                  filename="corpusmind-discourse-cooccurrence"
                />
              </div>
              <p className="coocc-hint">{t(lang, "discourse_coocc_hint")}</p>
              <div className="discourse-table-wrap">
                <table className="discourse-table">
                  <thead>
                    <tr>
                      <th>{t(lang, "discourse_coocc_pair")}</th>
                      <th className="num">{t(lang, "discourse_coocc_sentences")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.data.cooccurrence.map((p) => (
                      <tr key={`${p.a}__${p.b}`}>
                        <td>
                          <strong>{p.a.replace(/_/g, " ")}</strong> × {p.b.replace(/_/g, " ")}
                        </td>
                        <td className="num">{p.sentences.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {/* v1.2.7 (§4): radar over the 15 dimensions before the table */}
          {isPersuasion && result.data.categories && Object.keys(result.data.categories).length > 0 && (
            <PersuasionRadar categories={result.data.categories} />
          )}
          {/* v1.2.7 (§3): sortable DataTable - replaces the v1.2.6 card list.
              DP is always available; LL / Log Ratio / %DIFF / SM appear when
              a comparison corpus is selected. The Examples column keeps the
              evidence list from the old cards behind an expandable row. */}
          <div className="discourse-table-wrap">
            <table className="discourse-table">
              <thead>
                <tr>
                  {columns.map((col, i) => (
                    <th
                      key={`${col.key}-${i}`}
                      className={clsx(col.numeric && "num", col.key === sortKey && "sorted")}
                      aria-sort={
                        col.key === sortKey
                          ? sortDir === 1 ? "ascending" : "descending"
                          : undefined
                      }
                    >
                      {/* The examples column reuses the category key but must
                          not render as a sort control. */}
                      {i === columns.length - 1 ? (
                        <span>{t(lang, col.labelKey)}</span>
                      ) : (
                        <button
                          type="button"
                          className="discourse-sort-btn"
                          onClick={() => onSort(col.key)}
                          title={col.titleKey ? t(lang, col.titleKey) : undefined}
                        >
                          {t(lang, col.labelKey)}
                          {arrow(col.key)}
                        </button>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(({ cat, info }) => (
                  <tr key={cat}>
                    <td>
                      <strong>{cat}</strong>
                      {isUsas && (info.label || info.group) && (
                        <div className="cat-meta">
                          {info.label}
                          {info.group ? ` - ${info.group}` : ""}
                        </div>
                      )}
                    </td>
                    <td className="num" title={isPersuasion ? t(lang, "pi_freq_hint") : undefined}>
                      {fmtNum(info.freq, 1)}
                    </td>
                    <td className="num">{fmtNum(info.per_million, 2)}</td>
                    <td className="num" title={t(lang, "discourse_dp_hint")}>
                      {fmtNum(info.dp, 2)}
                    </td>
                    <td className="num" title={t(lang, "discourse_ll_hint")}>
                      {hasCompare ? (
                        <>
                          {fmtNum(info.log_likelihood ?? null, 2)}
                          {info.cochran_warning && (
                            <span className="discourse-cochran-flag" title={t(lang, "discourse_cochran_warning")}>*</span>
                          )}
                        </>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="num" title={t(lang, "discourse_lr_hint")}>
                      {hasCompare ? fmtNum(info.log_ratio ?? null, 2) : "-"}
                    </td>
                    <td className="num">{hasCompare ? fmtNum(info.pct_diff ?? null, 1) : "-"}</td>
                    <td className="num">{hasCompare ? fmtNum(info.simple_maths, 2) : "-"}</td>
                    <td>
                      {info.examples.length > 0 ? (
                        <details className="discourse-examples-details">
                          <summary>{t(lang, "discourse_examples_count").replace("{n}", String(info.examples.length))}</summary>
                          <ul className="discourse-examples">
                            {info.examples.map((ex, i) => (
                              <li key={i}>
                                {ex.evidence_id && <code className="evidence-ref">{ex.evidence_id}</code>}
                                <strong>{ex.cue}</strong>
                                {ex.sentence_preview && <em>"{ex.sentence_preview}…"</em>}
                              </li>
                            ))}
                          </ul>
                        </details>
                      ) : (
                        <span className="cat-meta">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="result-meta">
            {t(lang, "discourse_dp_hint")}
            {hasCompare && (
              <>
                {" · "}{t(lang, "discourse_ll_hint")}
                {anyCochran && (
                  <>
                    {" · "}
                    <strong>* </strong>
                    {t(lang, "discourse_cochran_warning")}
                  </>
                )}
              </>
            )}
          </div>
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


const EMOTION_COLORS: Record<string, string> = {
  joy: "var(--bar-positive)",
  sadness: "var(--bar-negative)",
  anger: "var(--tool4-accent)",
  fear: "var(--tool5-accent)",
  disgust: "var(--tool6-accent)",
  surprise: "var(--tool2-accent)",
  trust: "var(--tool1-accent)",
  anticipation: "var(--tool3-accent)",
};

function SentimentPanel({ cid }: { cid: string }) {
  const lang = useUI((s) => s.lang);
  const result = useQuery({
    queryKey: ["sentiment", cid],
    queryFn: () => api.sentiment(cid),
  });
  const exportStatus = useExportStatus();
  const d = result.data;
  const emoLabel = (e: string) => t(lang, `emo_${e}` as TranslationKey);

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="toolbar">
        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `sentiment.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      <div className="grounding-notice">
        <strong>{t(lang, "sent_note")}</strong>
      </div>

      {d && (
        <>
          <h3>{t(lang, "sent_layers_title")}</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "12px" }}>
            <span
              className="cat-meta"
              title={d.lexicons?.appraisal_cues?.note}
              style={{ border: "1px solid var(--border-strong)", borderRadius: "6px", padding: "2px 8px" }}
            >
              {t(lang, "sent_layer_appraisal")}:{" "}
              <strong>
                {d.appraisal?.available
                  ? t(lang, "sent_coverage_full")
                  : t(lang, "sent_layer_unavailable_ar")}
              </strong>
            </span>
            <span
              className="cat-meta"
              style={{ border: "1px solid var(--border-strong)", borderRadius: "6px", padding: "2px 8px" }}
            >
              {t(lang, "sent_layer_emotions")}:{" "}
              <strong>
                {d.lexicons?.emolex?.coverage === "full"
                  ? t(lang, "sent_coverage_full")
                  : t(lang, "sent_coverage_starter")}
              </strong>
            </span>
          </div>
          {d.lexicons?.emolex?.coverage !== "full" && d.lexicons?.emolex?.upgrade_hint && (
            <div className="cat-meta" style={{ marginBottom: "12px" }}>
              {d.lexicons.emolex.upgrade_hint}
            </div>
          )}

          <div className="result-meta">
            <strong>{d.total_sentences}</strong> sentences ·
            avg score = <strong>{d.avg_score}</strong> (-1 to +1) ·
            method = <strong>{d.method}</strong>
          </div>
          <div className="sentiment-bars">
            <div className="bar-row">
              <span className="bar-label">Positive</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(d.positive / d.total_sentences) * 100}%`, background: "var(--bar-positive)" }} /></div>
              <span className="bar-value">{d.positive}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Neutral</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(d.neutral / d.total_sentences) * 100}%`, background: "var(--bar-neutral)" }} /></div>
              <span className="bar-value">{d.neutral}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Negative</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(d.negative / d.total_sentences) * 100}%`, background: "var(--bar-negative)" }} /></div>
              <span className="bar-value">{d.negative}</span>
            </div>
          </div>

          {d.appraisal?.available && d.appraisal.categories && (
            <>
              <h3>{t(lang, "sent_appraisal_title")}</h3>
              <div className="sentiment-bars">
                {Object.entries(d.appraisal.categories).map(([cat, info]) => {
                  const max = Math.max(
                    ...Object.values(d.appraisal!.categories).map((c) => c.count),
                    1,
                  );
                  return (
                    <div className="bar-row" key={cat}>
                      <span className="bar-label" title={cat}>{cat.replace(/^\w+\./, "")}</span>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${(info.count / max) * 100}%`, background: cat.startsWith("attitude.") ? "var(--brand-500)" : "var(--tool2-accent)" }} />
                      </div>
                      <span className="bar-value">{info.count}</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {d.emotions && Object.values(d.emotions).some((v) => v > 0) && (
            <>
              <h3>{t(lang, "sent_emotions_title")}</h3>
              <div className="sentiment-bars">
                {Object.entries(d.emotions).map(([emotion, n]) => {
                  const max = Math.max(...Object.values(d.emotions!), 1);
                  return (
                    <div className="bar-row" key={emotion}>
                      <span className="bar-label">{emoLabel(emotion)}</span>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${(n / max) * 100}%`, background: EMOTION_COLORS[emotion] ?? "var(--brand-500)" }} />
                      </div>
                      <span className="bar-value">{n}</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {d.top_emotional && d.top_emotional.length > 0 && (
            <>
              <h3>{t(lang, "sent_top_words_title")}</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Lemma</th>
                    <th>Polarity</th>
                    <th>Emotions</th>
                    <th>Freq</th>
                  </tr>
                </thead>
                <tbody>
                  {d.top_emotional.map((w) => (
                    <tr key={w.lemma}>
                      <td>{w.lemma}</td>
                      <td style={{ color: w.polarity > 0 ? "var(--bar-positive)" : "var(--bar-negative)" }}>
                        {w.polarity > 0 ? t(lang, "sent_top_word_polarity_pos") : t(lang, "sent_top_word_polarity_neg")}
                      </td>
                      <td>{w.emotions.length > 0 ? w.emotions.map(emoLabel).join(", ") : "-"}</td>
                      <td>{w.freq}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h3>Sentiment timeline (per sentence) {d.timeline.length > 100 && <span style={{ fontSize: "12px", fontWeight: "normal", color: "var(--text-subtle)" }}>(showing first 100 of {d.timeline.length})</span>}</h3>
          <div className="sentiment-timeline">
            {d.timeline.slice(0, 100).map((tl, i) => (
              <div key={i} className="timeline-bar"
                style={{ height: `${Math.abs(tl.score) * 40 + 2}px`,
                         background: tl.score > 0 ? "var(--bar-positive)" : tl.score < 0 ? "var(--bar-negative)" : "var(--bar-neutral)" }}
                title={`Sent ${tl.sent}: score=${tl.score} (pos=${tl.pos_hits}, neg=${tl.neg_hits})${tl.dominant_emotion ? ` · ${t(lang, "sent_timeline_emotion")} ${emoLabel(tl.dominant_emotion)}` : ""}${tl.attitude && tl.attitude.length > 0 ? ` · ${tl.attitude.join(", ")}` : ""}`}
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
        TTR per document is sample-size-sensitive - compare documents of similar length.
      </div>
    </div>
  );
}

async function downloadTable(rows: (string | number)[][], headers: string[], _fmt: string): Promise<Blob> {
  // CSV serialization (client-side; the table is small - one row per document)
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
            <Stat label="Flesch Reading Ease" value={d.flesch_reading_ease != null ? d.flesch_reading_ease.toFixed(1) : "-"}
                  hint="100 = very easy, 0 = very difficult (English only)" />
            <Stat label="Flesch–Kincaid grade" value={d.flesch_kincaid_grade != null ? d.flesch_kincaid_grade.toFixed(1) : "-"}
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
            Columns show per-million frequencies in each metadata group -
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
  // v1.2.11: corpus language for script-correct KWIC cells (dir=auto + lang).
  const corpusMetaQ = useQuery({
    queryKey: ["corpus", cid],
    queryFn: () => api.getCorpus(cid),
  });
  const corpusLang = (corpusMetaQ.data?.language ?? "en").toLowerCase();
  const corpusScriptTag =
    corpusLang === "ur" ? "urdu" : corpusLang === "fa" ? "arabic" : corpusLang === "hi" ? "devanagari" : undefined;
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
            {data.note ? <span className="hint"> - {data.note}</span> : null}
          </div>
          {data.timing && (
            <div className="hint vk-timing">
              {t(lang, "vk_timing")
                .replace("{c}", String(data.timing.candidates_ms ?? "-"))
                .replace("{e}", String(data.timing.embed_ms ?? "-"))
                .replace("{s}", String(data.timing.search_ms ?? "-"))
                .replace("{t}", String(data.timing.total_ms ?? "-"))
                .replace("{b}", String(data.timing.similarity_backend ?? "numpy"))}
            </div>
          )}

          {data.lines.length === 0 ? (
            <div className="empty-state">{t(lang, "vk_no_lines")}</div>
          ) : (
            <table className="kwic-table" data-corpus-script={corpusScriptTag}>
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
                    <td className="left" dir="auto" lang={corpusLang}>{l.left}</td>
                    <td className="node" dir="auto" lang={corpusLang}>{l.node}</td>
                    <td className="right" dir="auto" lang={corpusLang}>{l.right}</td>
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
