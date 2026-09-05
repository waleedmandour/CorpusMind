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
import { ExportButton } from "@/components/ExportButton";

const LEVELS = ["word", "lemma", "pos", "root", "pattern"] as const;
const POS_COLORS: Record<string, string> = {
  NOUN: "pos-noun", VERB: "pos-verb", ADJ: "pos-adj", ADV: "pos-adv",
  DET: "pos-det", ADP: "pos-adp", PRON: "pos-pron", AUX: "pos-aux",
  PUNCT: "pos-punct", CCONJ: "pos-cconj", SCONJ: "pos-sconj",
};
const PAGE_SIZE = 200;

export function ConcordancerView() {
  const cid = useApp((s) => s.activeCorpusId);
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<typeof LEVELS[number]>("word");
  const [window, setWindow] = useState(5);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [randomSample, setRandomSample] = useState(false);
  const [regex, setRegex] = useState(false);
  // v1.0.1 KWIC sort: up to 3 levels, each (side, offset)
  const [sortLevels, setSortLevels] = useState<ConcordanceSortSpec[]>([]);
  // Issue 17 fix: the toggle previously did nothing — random_sample was never
  // sent and the engine had no sampling support. The seed is now generated
  // per search, echoed back by the engine in query.sample_seed, and shown in
  // the result metadata so the sample is reproducible.
  const [sampleSeed, setSampleSeed] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [submitted, setSubmitted] = useState<{ q: string; l: string; w: number; cs: boolean; rs: boolean; seed: number | null; rx: boolean; sort: ConcordanceSortSpec[] } | null>(null);
  // Issue 5: visible export status so the user knows what happened
  const [exportStatus, setExportStatus] = useState<{ kind: "success" | "error" | "info"; msg: string } | null>(null);

  const result = useQuery({
    queryKey: ["concordance", cid, submitted, offset],
    queryFn: () => api.concordance(cid!, submitted!.q, submitted!.l as any, submitted!.w, PAGE_SIZE, offset, submitted!.cs, submitted!.rs ? 100 : null, submitted!.seed, submitted!.rx, submitted!.sort),
    enabled: !!cid && !!submitted,
  });

  const onSearch = () => {
    if (!query.trim()) return;
    setOffset(0);
    setSampleSeed(randomSample ? Math.floor(Math.random() * 1_000_000) : null);
    setSubmitted({ q: query.trim(), l: level, w: window, cs: caseSensitive, rs: randomSample, seed: sampleSeed, rx: regex, sort: sortLevels });
  };

  // Issue 5: wrap in exportWithFeedback so both backend errors (engine
  // offline, 422, 500) and save-dialog errors (cancel, disk full, perms)
  // are surfaced to the user instead of failing silently.
  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!submitted || !cid) return;
    setExportStatus(null);
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
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="Search query (use * for wildcard, e.g. 'fox*' or 'NOUN')"
          className="search-input"
        />
        <select value={level} onChange={(e) => setLevel(e.target.value as any)}>
          {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
        <label>Window
          <input type="number" min={1} max={20} value={window}
                 onChange={(e) => setWindow(Number(e.target.value))} />
        </label>
        <label title="Python-style regular expressions, e.g. ca[bt]|dog">
          <input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} />
          Regex
        </label>
        <label title="Match case exactly (e.g. 'Fox' vs 'fox')">
          <input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />
          Case sensitive
        </label>
        <label title="Randomize result order (reproducible with same seed)">
          <input type="checkbox" checked={randomSample} onChange={(e) => setRandomSample(e.target.checked)} />
          Random sample
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

      {exportStatus && exportStatus.msg && (
        <div className={clsx("uploader-status", exportStatus.kind)} style={{ marginTop: "var(--space-2)" }}>
          {exportStatus.msg}
        </div>
      )}

      {result.isLoading && <div className="empty-state">Searching...</div>}
      {result.isError && <div className="error">Error: {String(result.error)}</div>}
      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total.toLocaleString()}</strong> match{result.data.total === 1 ? "" : "es"}
            {" "}for <code>{String(result.data.query.q)}</code> ({String(result.data.query.level)} level)
            {result.data.query.regex ? " (regex)" : ""}
            {query.trim().includes(" ") && !regex && " (phrase)"}
            {caseSensitive && " (case sensitive)"}
            {submitted?.rs && " (random sample of 100, seed " + (result.data.query.sample_seed ?? submitted.seed) + ")"}
            {submitted?.sort?.length ? " (sorted " + submitted.sort.map((s) => (s.side === "left" ? "L" : "R") + s.offset).join(", ") + ")" : ""}
            {result.data.query.total_capped ? " (match set capped at 20,000 — total is a lower bound)" : ""}
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
              <table className="kwic-table">
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
                      <td className="left">{l.left}</td>
                      <td className="node">{l.node}</td>
                      <td className="right">{l.right}</td>
                      <td><span className={clsx("pos-tag", POS_COLORS[l.pos] ?? "pos-other")}>{l.pos}</span></td>
                      <td className="lemma">{l.lemma}</td>
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
                  <span style={{ fontSize: "12px", color: "var(--text-subtle)" }}>
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
