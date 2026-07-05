/**
 * Analysis — frequency, collocation, keyness, dispersion (§8.5–8.9).
 *
 * The collocation view's measure selector and the keyness view's combined
 * significance + effect-size display are the load-bearing UI for §4
 * Principle 3: "Effect size and significance, always together."
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api, downloadBlob } from "@/lib/api";
import { useApp } from "@/store/app";

type Tab = "frequency" | "collocation" | "keyness" | "dispersion";

export function AnalysisView() {
  const cid = useApp((s) => s.activeCorpusId);
  const [tab, setTab] = useState<Tab>("frequency");

  if (!cid) return <div className="empty-state">Select a corpus to analyze.</div>;

  return (
    <div className="analysis">
      <div className="tabs">
        {(["frequency", "collocation", "keyness", "dispersion"] as Tab[]).map((t) => (
          <button key={t} className={clsx("tab", { active: tab === t })} onClick={() => setTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "frequency" && <FrequencyPanel cid={cid} />}
      {tab === "collocation" && <CollocationPanel cid={cid} />}
      {tab === "keyness" && <KeynessPanel cid={cid} />}
      {tab === "dispersion" && <DispersionPanel cid={cid} />}
    </div>
  );
}


function FrequencyPanel({ cid }: { cid: string }) {
  const [unit, setUnit] = useState<"word" | "lemma" | "pos">("word");
  const [minFreq, setMinFreq] = useState(1);
  const result = useQuery({
    queryKey: ["frequency", cid, unit, minFreq],
    queryFn: () => api.frequency(cid, unit, minFreq, 200),
  });

  const onExport = async () => {
    const blob = await api.exportFrequencyXlsx(cid, unit, 1000);
    downloadBlob(blob, `frequency_${unit}.xlsx`);
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Unit
          <select value={unit} onChange={(e) => setUnit(e.target.value as any)}>
            <option value="word">Word</option>
            <option value="lemma">Lemma</option>
            <option value="pos">POS tag</option>
          </select>
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <button onClick={onExport}>Export Excel</button>
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens ·
            <strong> {result.data.total_types.toLocaleString()}</strong> types ·
            STTR (1000-token chunks) = <strong>{result.data.sttr.toFixed(4)}</strong>
          </div>
          <DataTable
            headers={[unit, "Frequency", "Per million", "%"]}
            rows={result.data.rows.map((r) => [r.item, r.freq, r.per_million, r.percent])}
          />
        </>
      )}
    </div>
  );
}


function CollocationPanel({ cid }: { cid: string }) {
  const [node, setNode] = useState("");
  const [level, setLevel] = useState<"word" | "lemma">("lemma");
  const [window, setWindow] = useState(5);
  const [minFreq, setMinFreq] = useState(3);
  const [submitted, setSubmitted] = useState<{ n: string; l: string; w: number; mf: number } | null>(null);

  const result = useQuery({
    queryKey: ["collocations", cid, submitted],
    queryFn: () => api.collocations(cid, submitted!.n, submitted!.l as any, submitted!.w, submitted!.mf),
    enabled: !!submitted,
  });

  const onSearch = () => {
    if (!node.trim()) return;
    setSubmitted({ n: node.trim(), l: level, w: window, mf: minFreq });
  };

  const onExport = async () => {
    if (!submitted) return;
    const blob = await api.exportCollocationsXlsx(cid, submitted.n, submitted.l as any, submitted.w, submitted.mf);
    downloadBlob(blob, `collocations_${submitted.n}.xlsx`);
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
        <button onClick={onSearch} disabled={!node.trim()}>Compute</button>
        <button onClick={onExport} disabled={!result.data}>Export Excel</button>
      </div>

      <div className="grounding-notice">
        <strong>Reproducibility:</strong> every collocation result carries its window size
        and minimum frequency. A collocation measure without a stated window is not reproducible.
        All measures use the formulas in <code>docs/METHODOLOGY.md</code>.
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Node: <code>{result.data.node}</code> · Window ±{result.data.window} · Min freq {result.data.min_freq}
          </div>
          {result.data.rows.length === 0 ? (
            <div className="empty-state">No collocates met the min-frequency threshold.</div>
          ) : (
            <DataTable
              headers={["Collocate", "O", "f(node)", "f(y)", "N", ...measureKeys]}
              rows={result.data.rows.map((r) => [
                r.collocate, r.O, r.fx, r.fy, r.N,
                ...measureKeys.map((k) => (r as any)[k] ?? "—"),
              ])}
            />
          )}
        </>
      )}
    </div>
  );
}


function KeynessPanel({ cid }: { cid: string }) {
  const referenceCorpusId = useApp((s) => s.referenceCorpusId);
  const setReferenceCorpus = useApp((s) => s.setReferenceCorpus);
  const [minFreq, setMinFreq] = useState(5);

  // Need to list corpora in the active project to populate the reference picker
  const activeProjectId = useApp((s) => s.activeProjectId);
  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => api.listCorpora(activeProjectId!),
    enabled: !!activeProjectId,
  });

  const result = useQuery({
    queryKey: ["keyness", cid, referenceCorpusId, minFreq],
    queryFn: () => api.keyness(cid, referenceCorpusId!, minFreq, 200),
    enabled: !!referenceCorpusId,
  });

  const onExport = async () => {
    if (!referenceCorpusId) return;
    const blob = await api.exportKeynessXlsx(cid, referenceCorpusId);
    downloadBlob(blob, `keyness.xlsx`);
  };

  const onMethodsPdf = async () => {
    const blob = await api.exportMethodsPdf(cid);
    downloadBlob(blob, `methods_section.pdf`);
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Reference corpus
          <select value={referenceCorpusId ?? ""} onChange={(e) => setReferenceCorpus(e.target.value || null)}>
            <option value="">— Select —</option>
            {corpora.data?.filter((c) => c.id !== cid).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <button onClick={onExport} disabled={!result.data}>Export Excel</button>
        <button onClick={onMethodsPdf}>Methods PDF</button>
      </div>

      <div className="grounding-notice">
        <strong>§4 Principle 3:</strong> a "key" word is never reported as important on
        frequency-of-occurrence-in-a-huge-corpus grounds alone. Log Ratio, %DIFF,
        Simple Maths, and Odds Ratio ride alongside log-likelihood — never report
        one without the other.
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Target N₁ = <strong>{result.data.N1.toLocaleString()}</strong> ·
            Reference N₂ = <strong>{result.data.N2.toLocaleString()}</strong>
          </div>
          <h3>Positive keywords (over-represented in target)</h3>
          <DataTable
            headers={["Term", "f1", "f2", "LL", "χ²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio"]}
            rows={result.data.positive_keywords.map((r) => [
              r.term, r.f1, r.f2, fmt(r.log_likelihood), fmt(r.chi_square),
              fmt(r.log_ratio), fmt(r.pct_diff), fmt(r.simple_maths), fmt(r.odds_ratio),
            ])}
          />
          <h3>Negative keywords (under-represented in target)</h3>
          <DataTable
            headers={["Term", "f1", "f2", "LL", "χ²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio"]}
            rows={result.data.negative_keywords.map((r) => [
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
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Juilland's D = <strong>{result.data.juillands_d}</strong> · Gries' DP = <strong>{result.data.gries_dp}</strong>
            <div className="hint">
              Juilland's D: 1 = perfectly even, 0 = maximally concentrated.
              Gries' DP: 0 = perfectly even, (n−1)/n = maximally concentrated.
            </div>
          </div>
          <h3>Frequency per document</h3>
          <div className="bar-chart">
            {result.data.per_part_freqs.map((f, i) => (
              <div key={i} className="bar-row">
                <span className="bar-label">Doc {i + 1}</span>
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
  return (
    <table className="data-table">
      <thead>
        <tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}


function fmt(v: number | null): string {
  if (v === null || v === undefined) return "—";
  if (!isFinite(v)) return v > 0 ? "∞" : "-∞";
  return v.toFixed(4);
}
