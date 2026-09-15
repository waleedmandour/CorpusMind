/**
 * Learner Research (v1.2.0) — three tools over learner corpora, mounted by
 * App.tsx with mode="caf" | "compare" | "errors" (sidebar: Learner Research).
 *
 *   caf     → CAF battery (Complexity–Accuracy–Fluency; Housen & Kuiken 2009)
 *             with optional grouping by L1 / CEFR proficiency, formulas +
 *             citations, and an AI-vs-learner comparator (learnerCafText).
 *   compare → CIA Compare (Granger 1998): learner corpus vs an engine
 *             reference corpus, a bundled reference frequency list, or a
 *             second learner corpus (L1-vs-L1) — keyness + CAF deltas.
 *   errors  → rule-based error CANDIDATES (ERRANT-lineage seed rules).
 *             Candidates need human verification before counting.
 *
 * Every panel follows the AnalysisView conventions: toolbar label/input rows,
 * useQuery/useMutation, .hint notices, and client-side table export via the
 * ExportButton + serializeTable pattern.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import {
  api,
  exportWithFeedback,
  type ExportFormat,
  type CafIndices,
} from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";
import { ExportButton } from "@/components/ExportButton";

// ─── Client-side export helpers (same pattern as AnalysisView) ──────────
// AnalysisView keeps downloadJsonResult/serializeTable module-private, so the
// Learner views ship a compact copy that works on pre-flattened rows.

function serializeTable(headers: string[], rows: string[][], fmt: string): Uint8Array {
  if (fmt === "csv" || fmt === "tsv") {
    const delim = fmt === "csv" ? "," : "\t";
    const lines = [headers.join(delim)];
    for (const row of rows) {
      lines.push(row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(delim));
    }
    // UTF-8 BOM for Excel compatibility
    return new TextEncoder().encode("\uFEFF" + lines.join("\n"));
  }
  if (fmt === "txt") {
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
  // xlsx and anything else: HTML table Excel can open (same fallback as AnalysisView)
  const lines = [
    '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">',
    "<head><meta charset=\"utf-8\"></head><body><table border=\"1\">",
    "<tr>" + headers.map((h) => `<th>${h.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</th>`).join("") + "</tr>",
    ...rows.map((r) => "<tr>" + r.map((c) => `<td>${c.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;")}</td>`).join("") + "</tr>"),
    "</table></body></html>",
  ];
  return new TextEncoder().encode(lines.join(""));
}

/** Download a pre-flattened table (headers + rows) in the requested format. */
async function downloadTableResult(
  headers: string[],
  rows: string[][],
  filename: string,
  setStatus: (msg: string, kind: "success" | "error" | "info") => void,
) {
  const ext = filename.split(".").pop()?.toLowerCase() || "csv";
  let blob: Blob;
  if (ext === "json") {
    blob = new Blob([JSON.stringify({ headers, rows }, null, 2)], { type: "application/json" });
  } else {
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
  await exportWithFeedback(async () => blob, filename, setStatus);
}

// ─── Shared export-status hook (same shape as AnalysisView.useExportStatus) ──
function useLearnerExportStatus() {
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

// ─── CAF index registry ─────────────────────────────────────────────────
// key = CafIndices field, i18n = label key (description key = i18n + "_d"),
// dec = decimals (MTLD is conventionally reported to 2).
const INDEX_KEYS: { key: keyof CafIndices; i18n: TranslationKey; dec: number }[] = [
  { key: "ttr", i18n: "lr_f_ttr", dec: 4 },
  { key: "mattr", i18n: "lr_f_mattr", dec: 4 },
  { key: "mtld", i18n: "lr_f_mtld", dec: 2 },
  { key: "hd_d", i18n: "lr_f_hdd", dec: 4 },
  { key: "guiraud", i18n: "lr_f_guiraud", dec: 4 },
  { key: "mean_sentence_length", i18n: "lr_f_msl", dec: 4 },
  { key: "sentence_length_stdev", i18n: "lr_f_sls", dec: 4 },
  { key: "mean_clause_length", i18n: "lr_f_mcl", dec: 4 },
  { key: "clauses_per_sentence", i18n: "lr_f_cps", dec: 4 },
  { key: "mean_word_length", i18n: "lr_f_mwl", dec: 4 },
  { key: "root_type_ratio", i18n: "lr_f_rtr", dec: 4 },
  { key: "error_free_sentence_ratio", i18n: "lr_f_efsr", dec: 4 },
  { key: "error_candidates_per_100", i18n: "lr_f_ec100", dec: 4 },
  { key: "spelling_candidate_rate", i18n: "lr_f_scr", dec: 4 },
];

/** null = not computable (missing parse/morph layer) → render "—", never 0. */
function fmtVal(v: number | null | undefined, dec = 4): string {
  if (v === null || v === undefined) return "—";
  if (!isFinite(v)) return String(v);
  return v.toFixed(dec);
}

function cafValue(caf: CafIndices | undefined, key: keyof CafIndices, dec = 4): string {
  if (!caf) return "—";
  return fmtVal(caf[key] as number | null | undefined, dec);
}

// =========================================================================
// Shell
// =========================================================================

export function LearnerResearchView({ mode }: { mode: "caf" | "compare" | "errors" }) {
  const lang = useUI((s) => s.lang);
  const cid = useApp((s) => s.activeCorpusId);
  const setActiveNav = useUI((s) => s.setActiveNav);

  if (!cid) {
    return (
      <div className="learner-view">
        <div className="empty-state">
          {t(lang, "lr_no_corpus")}
          <div style={{ marginTop: "var(--space-3)" }}>
            <button onClick={() => setActiveNav("corpus-target")}>
              {t(lang, "nav_corpus_target")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (mode === "caf") return <CafPanel cid={cid} lang={lang} />;
  if (mode === "compare") return <CiaComparePanel cid={cid} lang={lang} />;
  return <ErrorPatternsPanel cid={cid} lang={lang} />;
}

// =========================================================================
// mode="caf" — CAF battery + AI comparator
// =========================================================================

function CafPanel({ cid, lang }: { cid: string; lang: "en" | "ar" }) {
  const [groupBy, setGroupBy] = useState<"none" | "l1" | "proficiency">("none");
  const exportStatus = useLearnerExportStatus();

  const result = useQuery({
    queryKey: ["learner-caf", cid, groupBy],
    queryFn: () => api.learnerCaf(cid, groupBy),
  });

  const data = result.data;

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!data) return;
    // Flattened rows: index, value, description (overall corpus).
    const headers = ["index", "value", "description"];
    const rows = INDEX_KEYS.map((e) => [
      t(lang, e.i18n),
      cafValue(data.overall.caf, e.key, e.dec),
      // Every lr_f_* registry entry has a paired "..._d" description key.
      t(lang, `${e.i18n}_d` as TranslationKey),
    ]);
    const safeName = (data.corpus.name || cid).replace(/[^\w.-]+/g, "_").slice(0, 60);
    await downloadTableResult(headers, rows, `caf_${safeName}.${fmt as ExportFormat}`, exportStatus.set);
  };

  const corpus = data?.corpus;
  const overall = data?.overall;
  const metaBits = corpus
    ? [corpus.name, corpus.language, ...(corpus.l1 ? [corpus.l1] : []), ...(corpus.proficiency ? [corpus.proficiency] : [])]
    : [];

  return (
    <div className="learner-view">
      <header className="learner-header">
        <h2>{t(lang, "lr_caf_title")}</h2>
        <p className="hint">{t(lang, "lr_caf_sub")}</p>
      </header>

      <div className="toolbar">
        <label>
          {t(lang, "lr_group_by")}
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value as typeof groupBy)}>
            <option value="none">{t(lang, "lr_group_none")}</option>
            <option value="l1">{t(lang, "lr_group_l1")}</option>
            <option value="proficiency">{t(lang, "lr_group_proficiency")}</option>
          </select>
        </label>
        <ExportButton label={t(lang, "lr_export")} onExport={onExport} disabled={!data} />
      </div>
      {exportStatus.el}

      {result.isLoading && <div className="empty-state">Loading…</div>}
      {result.isError && <div className="error">Error: {String(result.error)}</div>}

      {data && (
        <>
          <div className="result-meta">
            {metaBits.map((b, i) => (
              <span key={i}>{i > 0 && " · "}<strong>{b}</strong></span>
            ))}
            {" · "}{overall!.caf.documents} documents ·{" "}
            {overall!.caf.tokens.toLocaleString()} tokens ·{" "}
            {overall!.caf.sentences.toLocaleString()} sentences
          </div>

          {/* OVERALL index table: label + value + description */}
          <table className="learner-index-table">
            <thead>
              <tr>
                <th>{t(lang, "lr_overall")}</th>
                <th>Value</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {INDEX_KEYS.map((e) => (
                <tr key={e.key}>
                  <td className="learner-index-name">{t(lang, e.i18n)}</td>
                  <td className="learner-index-value">{cafValue(overall!.caf, e.key, e.dec)}</td>
                  <td className="learner-index-desc">{t(lang, `${e.i18n}_d` as TranslationKey)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Sentence-length histogram (inline bar list) */}
          {overall!.caf.sentence_length_histogram && Object.keys(overall!.caf.sentence_length_histogram).length > 0 && (
            <div className="learner-group-card">
              <h4>{t(lang, "lr_f_slh")}</h4>
              <p className="hint">{t(lang, "lr_f_slh_d")}</p>
              <div className="learner-histogram">
                {Object.entries(overall!.caf.sentence_length_histogram).map(([bucket, n]) => {
                  const max = Math.max(...Object.values(overall!.caf.sentence_length_histogram), 1);
                  return (
                    <div key={bucket} className="bar-row">
                      <span className="bar-label">{bucket}</span>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${(n / max) * 100}%` }} />
                      </div>
                      <span className="bar-value">{n.toLocaleString()}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Per-group tables (when grouped) */}
          {groupBy !== "none" && data.groups.length > 0 && (
            <div className="learner-group-card">
              <h4>{t(lang, "lr_group_by")}: {groupBy === "l1" ? t(lang, "lr_group_l1") : t(lang, "lr_group_proficiency")}</h4>
              <table className="learner-index-table">
                <thead>
                  <tr>
                    <th>{groupBy === "l1" ? t(lang, "lr_group_l1") : t(lang, "lr_group_proficiency")}</th>
                    <th>Docs</th>
                    <th>Tokens</th>
                    <th>{t(lang, "lr_f_ttr")}</th>
                    <th>{t(lang, "lr_f_mattr")}</th>
                    <th>{t(lang, "lr_f_mtld")}</th>
                    <th>{t(lang, "lr_f_hdd")}</th>
                    <th>{t(lang, "lr_f_guiraud")}</th>
                    <th>{t(lang, "lr_f_msl")}</th>
                    <th>{t(lang, "lr_f_efsr")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.groups.map((g) => (
                    <tr key={g.name}>
                      <td className="learner-index-name">{g.name}</td>
                      <td>{g.documents}</td>
                      <td>{g.tokens.toLocaleString()}</td>
                      <td>{cafValue(g.caf, "ttr")}</td>
                      <td>{cafValue(g.caf, "mattr")}</td>
                      <td>{cafValue(g.caf, "mtld", 2)}</td>
                      <td>{cafValue(g.caf, "hd_d")}</td>
                      <td>{cafValue(g.caf, "guiraud")}</td>
                      <td>{cafValue(g.caf, "mean_sentence_length")}</td>
                      <td>{cafValue(g.caf, "error_free_sentence_ratio")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Formulas + citations in <details> blocks */}
          <details className="learner-details">
            <summary>{t(lang, "lr_formulas")}</summary>
            <table className="learner-index-table">
              <tbody>
                {Object.entries(data.formulas).map(([k, v]) => (
                  <tr key={k}>
                    <td className="learner-index-name"><code>{k}</code></td>
                    <td className="learner-index-desc">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
          <details className="learner-details">
            <summary>{t(lang, "lr_citations")}</summary>
            <ul className="learner-citations">
              {data.citations.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          </details>

          {/* Methodological notes */}
          {overall!.caf.notes.length > 0 && (
            <div className="learner-group-card">
              <h4>{t(lang, "lr_notes")}</h4>
              <ul className="learner-notes">
                {overall!.caf.notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </div>
          )}

          {/* AI vs learner comparator */}
          <AiComparator cid={cid} corpusLanguage={corpus!.language} />
        </>
      )}
    </div>
  );
}

function AiComparator({ cid, corpusLanguage }: { cid: string; corpusLanguage: string }) {
  const lang = useUI((s) => s.lang);
  const [text, setText] = useState("");
  const [lang2, setLang2] = useState<"en" | "ar">(corpusLanguage === "ar" ? "ar" : "en");
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.learnerCafText(text.trim(), lang2, cid),
    onSuccess: () => setErrMsg(null),
    // 503 (spaCy model missing) and other failures surface as plain text.
    onError: (e: Error) => setErrMsg(e.message),
  });

  const data = mutation.data;

  return (
    <div className="learner-group-card">
      <h3>{t(lang, "lr_ai_title")}</h3>
      <p className="hint">{t(lang, "lr_ai_sub")}</p>
      <label>
        {t(lang, "lr_ai_text")}
        <textarea
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t(lang, "lr_ai_text_ph")}
          className="learner-ai-textarea"
        />
      </label>
      <div className="toolbar">
        <label>
          {t(lang, "lr_err_language")}
          <select value={lang2} onChange={(e) => setLang2(e.target.value as "en" | "ar")}>
            <option value="en">en</option>
            <option value="ar">ar</option>
          </select>
        </label>
        <button onClick={() => mutation.mutate()} disabled={!text.trim() || mutation.isPending}>
          {mutation.isPending ? "…" : t(lang, "lr_ai_run")}
        </button>
      </div>

      {errMsg && <div className="error">{errMsg}</div>}

      {data && (
        <>
          <h4>{t(lang, "lr_ai_deltas")}</h4>
          <table className="learner-index-table">
            <thead>
              <tr>
                <th>{t(lang, "lr_overall")}</th>
                <th>Corpus</th>
                <th>AI text</th>
                <th>Δ</th>
              </tr>
            </thead>
            <tbody>
              {INDEX_KEYS.map((e) => (
                <tr key={e.key}>
                  <td className="learner-index-name">{t(lang, e.i18n)}</td>
                  <td>{data.corpus_caf ? cafValue(data.corpus_caf, e.key, e.dec) : "—"}</td>
                  <td>{cafValue(data.text_caf, e.key, e.dec)}</td>
                  <td className="learner-index-value">
                    {data.deltas && data.deltas[e.key] !== undefined && data.deltas[e.key] !== null
                      ? (data.deltas[e.key] as number).toFixed(e.dec)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.notes.length > 0 && (
            <ul className="learner-notes">
              {data.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

// =========================================================================
// mode="compare" — CIA Compare (Granger 1998)
// =========================================================================

function CiaComparePanel({ cid, lang }: { cid: string; lang: "en" | "ar" }) {
  const activeProjectId = useApp((s) => s.activeProjectId);
  const [referenceCorpusId, setReferenceCorpusId] = useState("");
  const [referenceList, setReferenceList] = useState("");
  const [compareCorpusId, setCompareCorpusId] = useState("");
  const [minFreq, setMinFreq] = useState(5);
  const exportStatus = useLearnerExportStatus();

  // Same listing approach as KeynessPanel: corpora of the active project for
  // the engine-corpus pickers + installed bundled reference frequency lists.
  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => api.listCorpora(activeProjectId!),
    enabled: !!activeProjectId,
  });
  const refCorpora = useQuery({
    queryKey: ["reference-corpora"],
    queryFn: () => api.listReferenceCorpora(),
  });

  const runMutation = useMutation({
    mutationFn: () =>
      api.learnerCia(cid, {
        ...(referenceCorpusId ? { reference_corpus_id: referenceCorpusId } : {}),
        ...(referenceList ? { reference_list: referenceList } : {}),
        ...(compareCorpusId ? { compare_corpus_id: compareCorpusId } : {}),
        min_freq: minFreq,
      }),
  });

  const data = runMutation.data;
  const nothingSelected = !referenceCorpusId && !referenceList && !compareCorpusId;

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!data?.keyness) return;
    const headers = ["term", "f1", "f2", "log_likelihood", "log_ratio", "set"];
    const rows: string[][] = [
      ...data.keyness.positive_keywords.map((r) => [
        r.term, String(r.f1), String(r.f2), String(r.log_likelihood ?? ""), String(r.log_ratio ?? ""), "+",
      ]),
      ...data.keyness.negative_keywords.map((r) => [
        r.term, String(r.f1), String(r.f2), String(r.log_likelihood ?? ""), String(r.log_ratio ?? ""), "-",
      ]),
    ];
    await downloadTableResult(headers, rows, `cia_compare_${cid.slice(0, 8)}.${fmt as ExportFormat}`, exportStatus.set);
  };

  const fmtN = (v: number | null | undefined): string =>
    v === null || v === undefined ? "—" : Number(v).toFixed(4);

  return (
    <div className="learner-view">
      <header className="learner-header">
        <h2>{t(lang, "lr_compare_title")}</h2>
        <p className="hint">{t(lang, "lr_compare_sub")}</p>
      </header>

      <div className="toolbar">
        <label>
          {t(lang, "lr_cia_reference")}
          <select value={referenceCorpusId} onChange={(e) => setReferenceCorpusId(e.target.value)}>
            <option value="">- None -</option>
            {(corpora.data ?? []).filter((c) => c.id !== cid).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        {(refCorpora.data?.references.filter((r) => r.installed).length ?? 0) > 0 && (
          <label>
            {t(lang, "lr_cia_reference_list")}
            <select
              value={referenceList}
              onChange={(e) => setReferenceList(e.target.value)}
              disabled={!!referenceCorpusId}
            >
              <option value="">- None -</option>
              {refCorpora.data?.references.filter((r) => r.installed).map((r) => (
                <option key={r.name} value={r.name}>{r.display_name}</option>
              ))}
            </select>
          </label>
        )}
        <label>
          {t(lang, "lr_cia_compare_corpus")}
          <select value={compareCorpusId} onChange={(e) => setCompareCorpusId(e.target.value)}>
            <option value="">- None -</option>
            {(corpora.data ?? []).filter((c) => c.id !== cid && c.id !== referenceCorpusId).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        <label>
          Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <button onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
          {runMutation.isPending ? "…" : t(lang, "lr_run")}
        </button>
        <ExportButton label={t(lang, "lr_export")} onExport={onExport} disabled={!data?.keyness} />
      </div>
      {exportStatus.el}

      {runMutation.isPending && <div className="empty-state">Running…</div>}
      {runMutation.isError && <div className="error">Error: {String(runMutation.error)}</div>}
      {nothingSelected && <div className="hint">{t(lang, "lr_cia_none")}</div>}

      {data && (
        <>
          {data.warnings.map((w, i) => (
            <div key={i} className="hint">⚠ {w}</div>
          ))}

          {/* Keyness (learner − reference) */}
          {data.keyness && (
            <>
              <h3>{t(lang, "lr_cia_keyness")}</h3>
              <h4>{t(lang, "lr_cia_keywords_pos")}</h4>
              <table className="learner-index-table">
                <thead>
                  <tr>
                    <th>Term</th><th>f1</th><th>f2</th><th>LL</th><th>Log Ratio</th>
                  </tr>
                </thead>
                <tbody>
                  {data.keyness.positive_keywords.slice(0, 20).map((r) => (
                    <tr key={r.term}>
                      <td className="learner-index-name">{r.term}</td>
                      <td>{r.f1}</td>
                      <td>{r.f2}</td>
                      <td>{fmtN(r.log_likelihood)}</td>
                      <td>{fmtN(r.log_ratio)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h4>{t(lang, "lr_cia_keywords_neg")}</h4>
              <table className="learner-index-table">
                <thead>
                  <tr>
                    <th>Term</th><th>f1</th><th>f2</th><th>LL</th><th>Log Ratio</th>
                  </tr>
                </thead>
                <tbody>
                  {data.keyness.negative_keywords.slice(0, 20).map((r) => (
                    <tr key={r.term}>
                      <td className="learner-index-name">{r.term}</td>
                      <td>{r.f1}</td>
                      <td>{r.f2}</td>
                      <td>{fmtN(r.log_likelihood)}</td>
                      <td>{fmtN(r.log_ratio)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {/* CAF deltas (reference/compare vs target) */}
          {Object.keys(data.deltas ?? {}).length > 0 && (
            <>
              <h3>{t(lang, "lr_cia_deltas")}</h3>
              {Object.entries(data.deltas).map(([arm, deltas]) => (
                <div key={arm} className="learner-group-card">
                  <h4><code>{arm}</code></h4>
                  <table className="learner-index-table">
                    <thead>
                      <tr><th>Index</th><th>Δ</th></tr>
                    </thead>
                    <tbody>
                      {INDEX_KEYS.map((e) => (
                        <tr key={e.key}>
                          <td className="learner-index-name">{t(lang, e.i18n)}</td>
                          <td className="learner-index-value">
                            {deltas[e.key] === undefined || deltas[e.key] === null ? "—" : (deltas[e.key] as number).toFixed(e.dec)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </>
          )}

          {data.citations.length > 0 && (
            <details className="learner-details">
              <summary>{t(lang, "lr_citations")}</summary>
              <ul className="learner-citations">
                {data.citations.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

// =========================================================================
// mode="errors" — Error-pattern candidates (human verification required)
// =========================================================================

const EN_RULES = ["en_article", "en_prep", "en_agreement", "en_spelling"];
const AR_RULES = ["ar_hamza", "ar_ta_marbuta", "ar_alef_maksura"];

function ErrorPatternsPanel({ cid, lang }: { cid: string; lang: "en" | "ar" }) {
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [rules, setRules] = useState<string[]>(EN_RULES);
  const [limit, setLimit] = useState(200);
  const exportStatus = useLearnerExportStatus();

  // Default the language (and rule set) from the corpus once it loads.
  const corpusQ = useQuery({
    queryKey: ["corpus", cid],
    queryFn: () => api.getCorpus(cid),
  });
  useEffect(() => {
    const l = corpusQ.data?.language;
    if (l) setLanguage(l.startsWith("ar") ? "ar" : "en");
  }, [corpusQ.data?.language]);
  useEffect(() => {
    setRules(language === "ar" ? AR_RULES : EN_RULES);
  }, [language]);

  const runMutation = useMutation({
    mutationFn: () => api.learnerErrors(cid, language, rules, limit),
  });

  const data = runMutation.data;
  const availableRules = language === "ar" ? AR_RULES : EN_RULES;

  const toggleRule = (rule: string) => {
    setRules((prev) => (prev.includes(rule) ? prev.filter((r) => r !== rule) : [...prev, rule]));
  };

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!data) return;
    const headers = ["rule_id", "word", "sentence", "line_ref", "reason"];
    const rows = data.candidates.map((c) => [c.rule_id, c.word, c.sentence, c.line_ref, c.reason]);
    await downloadTableResult(headers, rows, `error_candidates_${cid.slice(0, 8)}.${fmt as ExportFormat}`, exportStatus.set);
  };

  return (
    <div className="learner-view">
      <header className="learner-header">
        <h2>{t(lang, "lr_errors_title")}</h2>
        <p className="hint">{t(lang, "lr_errors_sub")}</p>
      </header>

      <div className="toolbar">
        <label>
          {t(lang, "lr_err_language")}
          <select value={language} onChange={(e) => setLanguage(e.target.value as "en" | "ar")}>
            <option value="en">en</option>
            <option value="ar">ar</option>
          </select>
        </label>
        <span className="learner-rules-row">
          <span>{t(lang, "lr_err_rules")}:</span>
          {availableRules.map((rule) => (
            <label key={rule} title={rule}>
              <input
                type="checkbox"
                checked={rules.includes(rule)}
                onChange={() => toggleRule(rule)}
              />
              {rule}
            </label>
          ))}
        </span>
        <label>
          Limit
          <input type="number" min={1} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
        </label>
        <button onClick={() => runMutation.mutate()} disabled={runMutation.isPending || rules.length === 0}>
          {runMutation.isPending ? "…" : t(lang, "lr_err_run")}
        </button>
        <ExportButton label={t(lang, "lr_export")} onExport={onExport} disabled={!data} />
      </div>
      {exportStatus.el}

      {runMutation.isPending && <div className="empty-state">Scanning…</div>}
      {runMutation.isError && <div className="error">Error: {String(runMutation.error)}</div>}

      {data && (
        <>
          {/* Verification gate — these are CANDIDATES, not errors. */}
          <div className="hint" role="status">{t(lang, "lr_err_verified_note")}</div>

          <div className="learner-counts" aria-label={t(lang, "lr_err_counts")}>
            <span className="learner-counts-label">{t(lang, "lr_err_counts")}:</span>
            {Object.entries(data.counts).map(([rule, n]) => (
              <span key={rule} className="learner-count-chip">{rule}: {n}</span>
            ))}
            <span className="learner-count-chip">total: {data.candidates.length}</span>
          </div>

          {data.candidates.length === 0 ? (
            <div className="empty-state">{t(lang, "lr_err_none")}</div>
          ) : (
            <table className="learner-index-table">
              <thead>
                <tr>
                  <th>{t(lang, "lr_err_rule")}</th>
                  <th>{t(lang, "lr_err_word")}</th>
                  <th>{t(lang, "lr_err_sentence")}</th>
                  <th>{t(lang, "lr_err_reason")}</th>
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((c, i) => (
                  <tr key={`${c.line_ref}-${c.rule_id}-${i}`}>
                    <td className="learner-index-name"><code>{c.rule_label || c.rule_id}</code></td>
                    <td>{c.word}</td>
                    <td className="learner-sentence"
                        dir={language === "ar" ? "rtl" : undefined}
                        lang={language === "ar" ? "ar" : undefined}>
                      {c.sentence}
                    </td>
                    <td className="learner-index-desc">{c.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {data.notes.length > 0 && (
            <ul className="learner-notes">
              {data.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
