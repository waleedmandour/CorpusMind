/**
 * Concordancer - KWIC view with color coding, sort, filter, stable line IDs.
 *
 * P1.2 improvements:
 * - Case-sensitive search toggle
 * - Pagination (Previous/Next 200)
 * - Random sample mode
 * v1.0.1 additions:
 * - Regex search toggle
 * - Phrase queries (whitespace in the query = multi-word sequence)
 * - KWIC sorting (AntConc-style L1/R1/L2/R2, up to 3 levels)
 * - root / pattern levels (Arabic morph layer)
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api, exportWithFeedback, type ExportFormat, type ConcordanceSortSpec } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";
import { SlowQueryNote } from "@/components/SlowQueryNote";
import { ExportButton } from "@/components/ExportButton";
// v1.2.13-1: CQL mode exports the fetched lines client-side — the engine's
// export endpoint re-runs a *simple* concordance query, which cannot express
// a CQL pattern, so calling it from CQL mode would silently export the wrong
// rows. The lines are already on screen; shaping is shared and unit-tested.
import { concordanceLinesToTable, downloadTable } from "@/lib/resultExport";

const LEVELS = ["word", "lemma", "pos", "root", "pattern"] as const;
const POS_COLORS: Record<string, string> = {
  NOUN: "pos-noun", VERB: "pos-verb", ADJ: "pos-adj", ADV: "pos-adv",
  DET: "pos-det", ADP: "pos-adp", PRON: "pos-pron", AUX: "pos-aux",
  PUNCT: "pos-punct", CCONJ: "pos-cconj", SCONJ: "pos-sconj",
};
const PAGE_SIZE = 200;

// v1.2.13-1: the engine wraps every HTTP failure as `HTTP <status>: <body>`;
// FastAPI body is {"detail": …}. Unwrap it so a CQL syntax error shows the
// position-annotated message ("Invalid CQL query: …col 12…") instead of raw
// JSON. Same parsing ArabicError has done since v1.2.11.
function engineErrorDetail(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (msg.startsWith("HTTP ")) {
    const i = msg.indexOf(": ");
    if (i > 0) {
      try {
        const parsed = JSON.parse(msg.slice(i + 2)) as { detail?: string };
        if (parsed?.detail) return String(parsed.detail);
      } catch {
        // body was not JSON; keep the raw text
      }
    }
  }
  return msg;
}

export function ConcordancerView() {
  const cid = useApp((s) => s.activeCorpusId);
  const lang = useUI((s) => s.lang);
  // v1.2.13-1: query mode — Simple (the single-node box) or CQL (token
  // sequences with attributes, gaps, alternation, within scoping; engine
  // endpoint POST /concordance/cql, engine/stats/cql.py documents grammar).
  const [mode, setMode] = useState<"simple" | "cql">("simple");
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<typeof LEVELS[number]>("word");
  const [window, setWindow] = useState(5);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [randomSample, setRandomSample] = useState(false);
  const [regex, setRegex] = useState(false);
  // v1.2.0: Arabic normalization before matching (alef/ya/ta-marbuta + dediac).
  const [normalizeArabic, setNormalizeArabic] = useState(false);
  // v1.0.1 KWIC sort: up to 3 levels, each (side, offset)
  const [sortLevels, setSortLevels] = useState<ConcordanceSortSpec[]>([]);
  // Issue 17 fix: the toggle previously did nothing — random_sample was never
  // sent and the engine had no sampling support. The seed is now generated
  // per search, echoed back by the engine in query.sample_seed, and shown in
  // the result metadata so the sample is reproducible.
  const [sampleSeed, setSampleSeed] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [submitted, setSubmitted] = useState<{ mode: "simple" | "cql"; q: string; l: string; w: number; cs: boolean; rs: boolean; seed: number | null; rx: boolean; sort: ConcordanceSortSpec[]; nm: boolean } | null>(null);
  // Issue 5: visible export status so the user knows what happened
  const [exportStatus, setExportStatus] = useState<{ kind: "success" | "error" | "info"; msg: string } | null>(null);

  // v1.2.11: corpus language drives script-correct rendering (dir=auto +
  // lang on KWIC cells) without touching the UI language.
  const corpusMeta = useQuery({
    queryKey: ["corpus", cid],
    queryFn: () => api.getCorpus(cid!),
    enabled: !!cid,
  });
  const corpusLang = (corpusMeta.data?.language ?? "en").toLowerCase();
  const corpusScriptTag =
    corpusLang === "ur" ? "urdu" : corpusLang === "fa" ? "arabic" : corpusLang === "hi" ? "devanagari" : undefined;

  const result = useQuery({
    queryKey: ["concordance", cid, submitted, offset],
    queryFn: () =>
      submitted!.mode === "cql"
        ? api.concordanceCql(cid!, {
            query: submitted!.q,
            window: submitted!.w,
            limit: PAGE_SIZE,
            offset,
            random_sample: submitted!.rs ? 100 : null,
            sample_seed: submitted!.seed,
            sort: submitted!.sort,
            normalize: submitted!.nm ? true : null,
            normalize_arabic: false,
          })
        : api.concordance(cid!, submitted!.q, submitted!.l as any, submitted!.w, PAGE_SIZE, offset, submitted!.cs, submitted!.rs ? 100 : null, submitted!.seed, submitted!.rx, submitted!.sort, submitted!.nm),
    enabled: !!cid && !!submitted,
    // v1.2.13-1: no TanStack-level retry. A CQL syntax error (422) is
    // deterministic — retrying it just delays the same message by the
    // default backoff (the same reasoning as the Arabic Tools hang fix);
    // connection-level restarts are already handled inside jsonFetch.
    retry: false,
  });

  const onSearch = () => {
    if (!query.trim()) return;
    setOffset(0);
    setSampleSeed(randomSample ? Math.floor(Math.random() * 1_000_000) : null);
    setSubmitted({ mode, q: query.trim(), l: level, w: window, cs: caseSensitive, rs: randomSample, seed: sampleSeed, rx: regex, sort: sortLevels, nm: normalizeArabic });
  };

  // v1.2.13-1: export — Simple mode keeps the server-side export (the engine
  // re-runs the query server-side and streams the file). CQL mode exports
  // the fetched lines client-side (see the concordanceLinesToTable note).
  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!submitted || !cid || !result.data) return;
    setExportStatus(null);
    if (submitted.mode === "cql") {
      const { headers, rows } = concordanceLinesToTable(result.data.lines);
      await downloadTable(headers, rows, `cql_concordance.${fmt}` as string, (msg, kind) => setExportStatus({ kind, msg }));
      return;
    }
    await exportWithFeedback(
      () => api.exportConcordance(cid, submitted.q, fmt as ExportFormat, submitted.l as any, submitted.w, 1000),
      `concordance_${submitted.q}.${fmt}`,
      (msg, kind) => setExportStatus({ kind, msg }),
    );
  };

  const total = result.data?.total ?? 0;
  const hasNext = offset + PAGE_SIZE < total;
  const hasPrev = offset > 0;

  if (!cid) return <div className="empty-state">Select a corpus to start searching. Go to <strong>Your Corpus</strong> in the sidebar.</div>;

  return (
    <div className="concordancer">
      <div className="search-bar">
        {/* v1.2.13-1: query mode — Simple single-node box or CQL-lite pattern
            (token sequences, gaps, alternation, within sentence|document). */}
        <div className="mode-toggle" role="group" aria-label="Query mode">
          <button
            type="button"
            className={clsx("mode-toggle-btn", { active: mode === "simple" })}
            onClick={() => setMode("simple")}
            title={t(lang, "cql_mode_simple_hint")}
          >
            {t(lang, "cql_mode_simple")}
          </button>
          <button
            type="button"
            className={clsx("mode-toggle-btn", { active: mode === "cql" })}
            onClick={() => setMode("cql")}
            title={t(lang, "cql_hint")}
          >
            CQL
          </button>
        </div>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder={mode === "cql" ? t(lang, "cql_placeholder") : "Search query (use * for wildcard, e.g. 'fox*' or 'NOUN')"}
          className="search-input"
          dir="auto"
        />
        {mode === "simple" && (
          <select value={level} onChange={(e) => setLevel(e.target.value as any)}>
            {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        )}
        <label>Window
          <input type="number" min={1} max={20} value={window}
                 onChange={(e) => setWindow(Number(e.target.value))} />
        </label>
        {/* Regex/case are simple-mode options: CQL carries its own flags
            (%c %d) and is case-sensitive by CQP convention. */}
        {mode === "simple" && (
          <label title="Python-style regular expressions, e.g. ca[bt]|dog">
            <input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} />
            Regex
          </label>
        )}
        {mode === "simple" && (
          <label title="Match case exactly (e.g. 'Fox' vs 'fox')">
            <input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />
            Case sensitive
          </label>
        )}
        <label title="Randomize result order (reproducible with same seed)">
          <input type="checkbox" checked={randomSample} onChange={(e) => setRandomSample(e.target.checked)} />
          Random sample
        </label>
        <label title={t(lang, "arb_normalize_hint")}>
          <input type="checkbox" checked={normalizeArabic} onChange={(e) => setNormalizeArabic(e.target.checked)} />
          {t(lang, "arb_normalize")}
        </label>
        <select
          value=""
          onChange={(e) => {
            const v = e.target.value as "left" | "right";
            if (v) setSortLevels((prev) => (prev.length < 3 ? [...prev, { side: v, offset: 1 }] : prev));
            e.target.value = "";
          }}
          title="Add a KWIC sort level (AntConc-style L1/R1/L2/R2)"
        >
          <option value="">+ Sort level</option>
          <option value="left">Sort L1</option>
          <option value="right">Sort R1</option>
        </select>
        {sortLevels.length > 0 && (
          <span className="sort-levels" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
            {sortLevels.map((s, i) => (
              <span key={i} className="pos-tag pos-other" style={{ cursor: "pointer" }}
                    title="Click to remove this sort level"
                    onClick={() => setSortLevels((prev) => prev.filter((_, j) => j !== i))}>
                {s.side === "left" ? "L" : "R"}{s.offset} ×
              </span>
            ))}
          </span>
        )}
        <button onClick={onSearch} disabled={!query.trim()}>Search</button>
        <ExportButton onExport={onExport} disabled={!submitted || !result.data} />
      </div>

      {/* v1.2.13-1: one-line CQL crib shown only in CQL mode. */}
      {mode === "cql" && (
        <div className="cql-hint" title={t(lang, "cql_hint")}>
          {t(lang, "cql_hint")}
        </div>
      )}

      {exportStatus && exportStatus.msg && (
        <div className={clsx("uploader-status", exportStatus.kind)} style={{ marginTop: "var(--space-2)" }}>
          {exportStatus.msg}
        </div>
      )}

      {result.isLoading && <div className="empty-state">Searching...</div>}
      {/* v1.2.10: queued-under-load feedback instead of a silent spinner. */}
      <SlowQueryNote pending={result.isLoading} lang={lang} />
      {/* v1.2.13-1: CQL syntax errors surface the engine's position-annotated
          detail ("Invalid CQL query: …") instead of a raw HTTP/JSON dump. */}
      {result.isError && (
        <div className="error" role="alert">
          Error: {engineErrorDetail(result.error)}
        </div>
      )}
      {result.data && submitted?.mode === "cql" && (
        <>
          <div className="result-meta">
            <strong>{result.data.total.toLocaleString()}</strong> match{result.data.total === 1 ? "" : "es"}
            {" "}for CQL <code>{String(result.data.query.q)}</code>
            {result.data.query.within ? ` within ${result.data.query.within}` : ""}
            {submitted?.nm && " (normalized)"}
            {submitted?.rs && " (random sample of 100, seed " + (result.data.query.sample_seed ?? submitted.seed) + ")"}
            {submitted?.sort?.length ? " (sorted " + submitted.sort.map((s) => (s.side === "left" ? "L" : "R") + s.offset).join(", ") + ")" : ""}
            {result.data.query.total_capped ? " (match set capped at 20,000 - total is a lower bound)" : ""}
            {total > PAGE_SIZE && (
              <span className="pagination-info">
                {" "} - showing {offset + 1}-{Math.min(offset + PAGE_SIZE, total)}
              </span>
            )}
          </div>

          {result.data.lines.length === 0 ? (
            <div className="empty-state">No matches.</div>
          ) : (
            <>
              <table className="kwic-table" data-corpus-script={corpusScriptTag}>
                <thead>
                  <tr>
                    <th>Line ID</th>
                    <th>Document</th>
                    <th className="right-align">Left context</th>
                    <th>Node</th>
                    <th>Right context</th>
                    <th>POS</th>
                    <th>Lemma</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.lines.map((l) => (
                    <tr key={l.line_id}>
                      <td className="line-id" title={l.line_id}>{l.line_id.slice(-12)}</td>
                      <td className="doc" title={l.document_filename}>{l.document_filename}</td>
                      <td className="left" dir="auto" lang={corpusLang}>{l.left}</td>
                      <td className="node" dir="auto" lang={corpusLang}>{l.node}</td>
                      <td className="right" dir="auto" lang={corpusLang}>{l.right}</td>
                      <td><span className={clsx("pos-tag", POS_COLORS[l.pos] ?? "pos-other")}>{l.pos}</span></td>
                      <td className="lemma" dir="auto" lang={corpusLang}>{l.lemma}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {total > PAGE_SIZE && (
                <div className="pagination-controls" style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginTop: "var(--space-3)", justifyContent: "center" }}>
                  <button
                    className="btn-small"
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                    disabled={!hasPrev || result.isFetching}
                  >
                    {"\u25C0"} Previous {PAGE_SIZE}
                  </button>
                  <span style={{ fontSize: "13px", color: "var(--text-subtle)" }}>
                    Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.ceil(total / PAGE_SIZE)}
                  </span>
                  <button
                    className="btn-small"
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                    disabled={!hasNext || result.isFetching}
                  >
                    Next {PAGE_SIZE} {"\u25B6"}
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
      {result.data && submitted?.mode !== "cql" && (
        <>
          <div className="result-meta">
            <strong>{result.data.total.toLocaleString()}</strong> match{result.data.total === 1 ? "" : "es"}
            {" "}for <code>{String(result.data.query.q)}</code> ({String(result.data.query.level)} level)
            {result.data.query.regex ? " (regex)" : ""}
            {query.trim().includes(" ") && !regex && " (phrase)"}
            {caseSensitive && " (case sensitive)"}
            {submitted?.nm && " (Arabic-normalized)"}
            {submitted?.rs && " (random sample of 100, seed " + (result.data.query.sample_seed ?? submitted.seed) + ")"}
            {submitted?.sort?.length ? " (sorted " + submitted.sort.map((s) => (s.side === "left" ? "L" : "R") + s.offset).join(", ") + ")" : ""}
            {result.data.query.total_capped ? " (match set capped at 20,000 - total is a lower bound)" : ""}
            {total > PAGE_SIZE && (
              <span className="pagination-info">
                {" "} - showing {offset + 1}-{Math.min(offset + PAGE_SIZE, total)}
              </span>
            )}
          </div>

          {result.data.lines.length === 0 ? (
            <div className="empty-state">No matches.</div>
          ) : (
            <>
              <table className="kwic-table" data-corpus-script={corpusScriptTag}>
                <thead>
                  <tr>
                    <th>Line ID</th>
                    <th>Document</th>
                    <th className="right-align">Left context</th>
                    <th>Node</th>
                    <th>Right context</th>
                    <th>POS</th>
                    <th>Lemma</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.lines.map((l) => (
                    <tr key={l.line_id}>
                      <td className="line-id" title={l.line_id}>{l.line_id.slice(-12)}</td>
                      <td className="doc" title={l.document_filename}>{l.document_filename}</td>
                      <td className="left" dir="auto" lang={corpusLang}>{l.left}</td>
                      <td className="node" dir="auto" lang={corpusLang}>{l.node}</td>
                      <td className="right" dir="auto" lang={corpusLang}>{l.right}</td>
                      <td><span className={clsx("pos-tag", POS_COLORS[l.pos] ?? "pos-other")}>{l.pos}</span></td>
                      <td className="lemma" dir="auto" lang={corpusLang}>{l.lemma}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {total > PAGE_SIZE && (
                <div className="pagination-controls" style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginTop: "var(--space-3)", justifyContent: "center" }}>
                  <button
                    className="btn-small"
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                    disabled={!hasPrev || result.isFetching}
                  >
                    {"\u25C0"} Previous {PAGE_SIZE}
                  </button>
                  <span style={{ fontSize: "13px", color: "var(--text-subtle)" }}>
                    Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.ceil(total / PAGE_SIZE)}
                  </span>
                  <button
                    className="btn-small"
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                    disabled={!hasNext || result.isFetching}
                  >
                    Next {PAGE_SIZE} {"\u25B6"}
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
