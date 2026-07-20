/**
 * Concordancer - KWIC view with color coding, sort, filter, stable line IDs.
 *
 * P1.2 improvements:
 * - Case-sensitive search toggle
 * - Pagination (Previous/Next 200)
 * - Random sample mode
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api, downloadBlob, type ExportFormat } from "@/lib/api";
import { useApp } from "@/store/app";
import { ExportButton } from "@/components/ExportButton";

const LEVELS = ["word", "lemma", "pos"] as const;
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
  const [offset, setOffset] = useState(0);
  const [submitted, setSubmitted] = useState<{ q: string; l: string; w: number; cs: boolean; rs: boolean } | null>(null);

  const result = useQuery({
    queryKey: ["concordance", cid, submitted, offset],
    queryFn: () => api.concordance(cid!, submitted!.q, submitted!.l as any, submitted!.w, PAGE_SIZE, offset, submitted!.cs),
    enabled: !!cid && !!submitted,
  });

  const onSearch = () => {
    if (!query.trim()) return;
    setOffset(0);
    setSubmitted({ q: query.trim(), l: level, w: window, cs: caseSensitive, rs: randomSample });
  };

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!submitted || !cid) return;
    const blob = await api.exportConcordance(cid, submitted.q, fmt as ExportFormat, submitted.l as any, submitted.w, 1000);
    downloadBlob(blob, `concordance_${submitted.q}.${fmt}`);
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
        <label title="Match case exactly (e.g. 'Fox' vs 'fox')">
          <input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />
          Case sensitive
        </label>
        <label title="Randomize result order (reproducible with same seed)">
          <input type="checkbox" checked={randomSample} onChange={(e) => setRandomSample(e.target.checked)} />
          Random sample
        </label>
        <button onClick={onSearch} disabled={!query.trim()}>Search</button>
        <ExportButton onExport={onExport} disabled={!submitted || !result.data} />
      </div>

      {result.isLoading && <div className="empty-state">Searching...</div>}
      {result.isError && <div className="error">Error: {String(result.error)}</div>}
      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total.toLocaleString()}</strong> match{result.data.total === 1 ? "" : "es"}
            {" "}for <code>{result.data.query.q as string}</code> ({result.data.query.level as string} level)
            {caseSensitive && " (case sensitive)"}
            {randomSample && " (randomized)"}
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
