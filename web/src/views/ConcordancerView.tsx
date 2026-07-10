/**
 * Concordancer — KWIC view with color coding, sort, filter, stable line IDs (§8.4).
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

export function ConcordancerView() {
  const cid = useApp((s) => s.activeCorpusId);
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<typeof LEVELS[number]>("word");
  const [window, setWindow] = useState(5);
  const [submitted, setSubmitted] = useState<{ q: string; l: string; w: number } | null>(null);

  const result = useQuery({
    queryKey: ["concordance", cid, submitted],
    queryFn: () => api.concordance(cid!, submitted!.q, submitted!.l as any, submitted!.w, 200),
    enabled: !!cid && !!submitted,
  });

  const onSearch = () => {
    if (!query.trim()) return;
    setSubmitted({ q: query.trim(), l: level, w: window });
  };

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!submitted || !cid) return;
    const blob = await api.exportConcordance(cid, submitted.q, fmt as ExportFormat, submitted.l as any, submitted.w, 1000);
    downloadBlob(blob, `concordance_${submitted.q}.${fmt}`);
  };

  if (!cid) return <div className="empty-state">Select a corpus to start searching.</div>;

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
        <button onClick={onSearch} disabled={!query.trim()}>Search</button>
        <ExportButton onExport={onExport} disabled={!submitted || !result.data} />
      </div>

      {result.isLoading && <div className="empty-state">Searching…</div>}
      {result.isError && <div className="error">Error: {String(result.error)}</div>}
      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total.toLocaleString()}</strong> match{result.data.total === 1 ? "" : "es"}
            {" "}for <code>{result.data.query.q as string}</code> ({result.data.query.level as string} level)
          </div>

          {result.data.lines.length === 0 ? (
            <div className="empty-state">No matches.</div>
          ) : (
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
          )}
        </>
      )}
    </div>
  );
}
