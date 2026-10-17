/**
 * ArabicView — 8.21 Arabic-specific analysis.
 *
 * Tools:
 *  - Morphology analyzer (root, pattern, lemma, POS, Buckwalter)
 *  - Root extractor (الجذر)
 *  - Clitic segmenter
 *  - Buckwalter transliterator
 *  - Dediacritizer
 *  - Normalizer
 *  - Dialect identifier
 *  - Register detector
 *
 * The view auto-detects Arabic input and flips to RTL layout.
 */
import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

// r4: downloadBlob + ArabicBulkResult — the corpus-mode report panel
// downloads the engine's full-depth JSON report next to the standard table
// export.
import { api, downloadBlob, type ArabicBulkResult, type ArabicBulkStatus } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";
import { useApp } from "@/store/app";
import { ArabicDataPackCard } from "@/components/ArabicDataPackCard";
// v1.2.13-1: Arabic Tools Export — the analysis results (morphology table,
// roots, clitics, transliteration, dialect/register distributions) can now be
// saved in the same xlsx/csv/tsv/txt/json formats as every other analysis
// panel. Shaping lives in lib/resultExport so it is unit-testable and shared
// with the other export paths.
import { ExportButton } from "@/components/ExportButton";
import { useExportStatus, downloadTable, arabicResultToTable } from "@/lib/resultExport";

type Tool = "morphology" | "roots" | "clitics" | "buckwalter" | "dediac" | "normalize" | "dialect" | "register" | "translate";

const TOOLS: { id: Tool; label: string; arabicLabel: string }[] = [
  { id: "morphology", label: "Morphology", arabicLabel: "التحليل الصرفي" },
  { id: "roots", label: "Roots", arabicLabel: "الجذور" },
  { id: "clitics", label: "Clitics", arabicLabel: "التصاقات" },
  { id: "buckwalter", label: "Buckwalter", arabicLabel: "بوكوالتر" },
  { id: "dediac", label: "Dediacritize", arabicLabel: "إزالة التشكيل" },
  { id: "normalize", label: "Normalize", arabicLabel: "التطبيع" },
  { id: "dialect", label: "Dialect ID", arabicLabel: "اللهجة" },
  { id: "register", label: "Register", arabicLabel: "السجل" },
  { id: "translate", label: "Translate", arabicLabel: "ترجمة" },
];

const SAMPLE_TEXTS = [
  "الطلاب يدرسون في المكتبة الكبيرة ويقرأون الكتب المفيدة",
  "يكتب الكاتب في المكتبة كتابا مفيدا للطلاب",
  "قال المعلم للطلاب إن الاجتهاد طريق النجاح",
];

// v1.2.0 (Issue 4): color-code POS tags instead of the grey 'pos-other'
// fallback. Handles both native CAMeL tags (noun, verb, adj, prep, ...) and
// UD UPOS tags (NOUN, VERB, ADP, ...) via one lookup.
const POS_CLASS_BY_TAG: Record<string, string> = {
  // CAMeL / Calima native
  noun: "pos-noun", noun_prop: "pos-noun", prop: "pos-noun",
  verb: "pos-verb", pseudo_verb: "pos-verb",
  adj: "pos-adj", adj_num: "pos-adj",
  adv: "pos-adv",
  prep: "pos-adp", prep_comp: "pos-adp",
  pron: "pos-pron", pron_dem: "pos-pron", pron_rel: "pos-pron", pron_inter: "pos-pron",
  conj: "pos-cconj", conj_sub: "pos-sconj",
  part: "pos-det", part_neg: "pos-det", part_focus: "pos-det", part_inter: "pos-det", part_voc: "pos-det",
  det: "pos-det",
  punct: "pos-punct",
  // UD UPOS
  NOUN: "pos-noun", PROPN: "pos-noun",
  VERB: "pos-verb", AUX: "pos-aux",
  ADJ: "pos-adj",
  ADV: "pos-adv",
  ADP: "pos-adp",
  PRON: "pos-pron",
  DET: "pos-det",
  CCONJ: "pos-cconj", SCONJ: "pos-sconj",
  PUNCT: "pos-punct",
};

function posClass(tag: string): string {
  return clsx("pos-tag", POS_CLASS_BY_TAG[tag] ?? "pos-other");
}

/**
 * v1.2.11 (Arabic Tools hang fix): error display for the Arabic Tools panel.
 * Surfaces the engine's `detail` (503 missing-data hint, 504 timeout hint)
 * instead of a raw `HTTP 503: {"detail": ...}` dump, so the spinner's error
 * state always lands on something actionable.
 *
 * v1.2.11 follow-up: a 503 caused by the MISSING DATA PACK renders the
 * in-app installer button right under the message (compact variant) so the
 * user can fix the machine without opening a terminal.
 */
export function isArabicDataMissingError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return (
    message.includes("503") &&
    /Arabic (morphology )?data is (not installed|incomplete)/.test(message)
  );
}

export function ArabicError({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  let detail = message;
  const httpIdx = message.indexOf(": ");
  if (message.startsWith("HTTP ") && httpIdx > 0) {
    const body = message.slice(httpIdx + 2);
    try {
      const parsed = JSON.parse(body) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      // body was not JSON; keep the raw text
    }
  }
  const dataMissing = isArabicDataMissingError(message);
  return (
    <div className="error" role="alert">
      Error: {detail}
      {dataMissing && (
        <div style={{ marginTop: "var(--space-3)" }}>
          <ArabicDataPackCard compact />
        </div>
      )}
    </div>
  );
}

const DIALECT_DBS: { id: "msa" | "egy" | "glf" | "lev"; label: string }[] = [
  { id: "msa", label: "MSA (calima-msa-r13)" },
  { id: "egy", label: "Egyptian (calima-egy-r13)" },
  { id: "glf", label: "Gulf (calima-glf-01)" },
  { id: "lev", label: "Levantine (calima-lev-01)" },
];

/** i18n placeholder fill ({name} -> value), same convention as ArabicDataPackCard. */
function fillVars(s: string, vars: Record<string, string>): string {
  let out = s;
  for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, v);
  return out;
}

export function ArabicView() {
  const [text, setText] = useState(SAMPLE_TEXTS[0]);
  const [tool, setTool] = useState<Tool>("morphology");
  const [dialect, setDialect] = useState<"msa" | "egy" | "glf" | "lev">("msa");
  // v1.2.0 (Issue 4): tagset selection for the morphology output —
  // native CAMeL/Calima tags or Universal Dependencies.
  const [tagset, setTagset] = useState<"calima" | "upos">("calima");
  const [submitted, setSubmitted] = useState<{ text: string; tool: Tool; dialect: string; tagset: string } | null>(null);
  const lang = useUI((s) => s.lang);
  const queryClient = useQueryClient();
  // v1.2.13-1: export feedback shared with the other analysis views.
  const exportStatus = useExportStatus();

  // --- r4: corpus mode — analyze a corpus uploaded in 'Your Corpus' ---
  // Two input sources, one panel: paste text (the per-tool endpoints), or
  // pick a pre-loaded Arabic corpus and let the engine run the chunked bulk
  // job over its STORED text (server-side load, progress, cancel, aggregated
  // report). The corpus workflow needs no copy-paste of megabytes.
  const [source, setSource] = useState<"text" | "corpus">("text");
  const [corpusId, setCorpusId] = useState("");
  // Bumped on every corpus run: fresh query keys mean the status/result
  // queries can never serve a previous job's payload.
  const [bulkRunId, setBulkRunId] = useState(0);
  const activeProjectId = useApp((s) => s.activeProjectId);
  const activeCorpusId = useApp((s) => s.activeCorpusId);
  const setActiveNav = useUI((s) => s.setActiveNav);

  const corporaQ = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => (activeProjectId ? api.listCorpora(activeProjectId) : Promise.resolve([])),
    enabled: source === "corpus" && !!activeProjectId,
  });
  // Only corpora whose language is Arabic — this is the Arabic Tools panel;
  // English corpora are irrelevant here (same filter the rest of the app
  // applies via the corpus language field).
  const arabicCorpora = (corporaQ.data ?? []).filter((c) => c.language === "ar");

  // Preselect the active corpus when it qualifies (the user just came from
  // Your Corpus with it loaded); otherwise the first Arabic corpus. Never
  // fight an explicit selection.
  useEffect(() => {
    if (source !== "corpus" || !corporaQ.data) return;
    if (arabicCorpora.some((c) => c.id === corpusId)) return;
    setCorpusId(
      activeCorpusId && arabicCorpora.some((c) => c.id === activeCorpusId)
        ? activeCorpusId
        : (arabicCorpora[0]?.id ?? ""),
    );
  }, [source, corporaQ.data, arabicCorpora, corpusId, activeCorpusId]);

  const bulkStatus = useQuery({
    queryKey: ["arabic-bulk-status", bulkRunId],
    queryFn: ({ signal }) => api.arabicBulkStatus(signal),
    enabled: bulkRunId > 0,
    // Poll ONLY while a job is running (same pattern as the data-pack
    // installer card). An idle job never schedules a fetch.
    refetchInterval: (q) => ((q.state.data as ArabicBulkStatus | undefined)?.busy ? 1_000 : false),
  });
  const bulkResult = useQuery({
    queryKey: ["arabic-bulk-result", bulkRunId],
    queryFn: ({ signal }) => api.arabicBulkResult(signal),
    enabled: bulkStatus.data?.state === "done",
    retry: false,
    gcTime: 0,
  });

  const startBulk = useMutation({
    mutationFn: (cid: string) => api.arabicBulkStartCorpus(cid),
    onSuccess: () => {
      // Race guard: the status query for the new runId key can fire BEFORE
      // the POST resolves and read the engine while it still reports idle —
      // after which nothing would ever schedule a poll (refetchInterval only
      // continues while busy). The engine answers start() only once the job
      // IS running, so refetching here always lands on "running".
      void queryClient.invalidateQueries({ queryKey: ["arabic-bulk-status"] });
    },
  });
  const cancelBulk = useMutation({ mutationFn: () => api.arabicBulkCancel() });

  // In flight = start request pending, a status fetch in flight, or the job
  // itself reporting busy. (Never read isPending off an enabled-gated
  // useQuery — scripts/check_query_pending.mjs guards exactly that.)
  const bulkBusy =
    startBulk.isPending || bulkStatus.isFetching || bulkStatus.data?.busy === true;
  const bulkSt = bulkStatus.data;
  const bulkPct =
    bulkSt && bulkSt.tokens_total
      ? Math.min(100, Math.round(((bulkSt.tokens_done ?? 0) / bulkSt.tokens_total) * 100))
      : 0;

  const onRunCorpus = () => {
    if (!corpusId || bulkBusy) return;
    setBulkRunId((n) => n + 1);
    startBulk.mutate(corpusId);
  };

  const backends = useQuery({ queryKey: ["arabic-backends"], queryFn: ({ signal }) => api.arabicBackends(signal) });

  // v1.2.11-rc1 fix: which dialect DBs are actually on disk. Shared cache
  // with the installer card (same queryKey), so it also refreshes right
  // after an in-app install finishes. Drives the Dialect DB dropdown: a DB
  // the installer never provisions is disabled with a plain-language suffix
  // instead of offering a request that can only ever end in 503.
  const installStatus = useQuery({
    queryKey: ["arabic-data-install"],
    queryFn: ({ signal }) => api.arabicDataInstallStatus(signal),
  });
  const morphDbs = installStatus.data?.camel_tools?.morphology_dbs;

  const result = useQuery({
    queryKey: ["arabic", submitted],
    queryFn: async ({ signal }) => {
      if (!submitted) return null;
      const t = submitted.text;
      switch (submitted.tool) {
        case "morphology":
          return { kind: "morphology" as const, data: await api.arabicAnalyze(t, submitted.dialect, (submitted.tagset as "calima" | "upos"), signal) };
        case "roots":
          return { kind: "roots" as const, data: await api.arabicRoots(t, signal) };
        case "clitics":
          return { kind: "clitics" as const, data: await api.arabicClitics(t, signal) };
        case "buckwalter":
          return { kind: "buckwalter" as const, data: await api.arabicBuckwalter(t, signal) };
        case "dediac":
          return { kind: "dediac" as const, data: await api.arabicDediacritize(t, signal) };
        case "normalize":
          return { kind: "normalize" as const, data: await api.arabicNormalize(t, signal) };
        case "dialect":
          return { kind: "dialect" as const, data: await api.arabicDialect(t, signal) };
        case "register":
          return { kind: "register" as const, data: await api.arabicRegister(t, signal) };
        case "translate":
          // For translate, we treat the input as a single word
          return { kind: "translate" as const, data: await api.translate(t.trim(), "ar-en") };
      }
    },
    enabled: !!submitted,
    // v1.2.11 (Arabic Tools hang fix): a re-submission must never serve a
    // cached failure or a stale pending state; and the default retry
    // behaviour would re-run the whole CAMeL analysis behind the user's
    // back. One request, one outcome, spinner always resolves.
    retry: false,
    gcTime: 0,
  });

  // v1.2.12 (field report: Arabic Tools stuck on a disabled "Analyzing… 0s"):
  // in TanStack Query v5 a query that has not run yet — `enabled: false`, i.e.
  // before the first click — reports `isPending === true` (status "pending",
  // fetchStatus "idle"). Using isPending as the in-flight flag therefore
  // rendered "Analyzing… 0s" + Cancel and DISABLED the Run button from the
  // moment the view opened, so no analysis could ever be started. "A request
  // is actually in flight" is `isFetching` (true only while fetchStatus is
  // "fetching"). Never use `isPending` for enabled-gated queries; see
  // scripts/check_query_pending.mjs (CI guard).
  const busy = result.isFetching;

  // v1.2.11 (Arabic Tools hang fix): elapsed-seconds ticker while a request
  // is in flight, so "Analyzing…" never looks like a silent freeze again.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!busy || !submitted) {
      setElapsed(0);
      return;
    }
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [busy, submitted]);

  const onCancel = () => {
    void queryClient.cancelQueries({ queryKey: ["arabic", submitted] });
  };

  const onRun = () => {
    if (!text.trim() || busy) return;
    const next = { text: text.trim(), tool, dialect, tagset };
    // v1.2.12: same inputs => same query key => setSubmitted would be a no-op
    // and the click would silently do nothing (e.g. retrying after an error
    // or after a Cancel). Ask for a fresh fetch explicitly in that case.
    if (submitted && JSON.stringify(submitted) === JSON.stringify(next)) {
      void result.refetch();
    } else {
      setSubmitted(next);
    }
  };

  // v1.2.11-rc1 fix: if the selected dialect DB turns out to be missing
  // (e.g. the dropdown state predates the status load, or the pack was
  // removed), fall back to MSA instead of sending a guaranteed-503 request.
  useEffect(() => {
    if (morphDbs && dialect !== "msa" && morphDbs[dialect] === false) {
      setDialect("msa");
    }
  }, [morphDbs, dialect]);

  return (
    <div className="arabic-view">
      <div className="grounding-notice">
        <strong>Note:</strong> Arabic is a first-class citizen, not a bolt-on. Backend: CAMeL Tools
        (calima-msa-r13). Roots (الجذر) and patterns (الوزن) are extracted via the
        SAMA/CALIMA-style morphological analyzer. Farasa and SinaTools are stubbed
        and can be swapped in without touching the rest of the engine.
      </div>

      {/* Backends */}
      {backends.data && (
        <div className="backends-bar">
          {backends.data.backends.map((b) => (
            <span key={b.name} className={clsx("backend-chip", { available: b.available })}>
              {b.name} {b.available ? `✓ (${b.model})` : "- stubbed"}
            </span>
          ))}
        </div>
      )}

      {/* r4: input source — paste text, or analyze a corpus uploaded in
          'Your Corpus' without leaving the panel. */}
      <div className="ar-source-toggle" role="tablist" aria-label={t(lang, "ar_source_label")}>
        <button
          role="tab"
          aria-selected={source === "text"}
          type="button"
          className={clsx("ar-source-btn", { active: source === "text" })}
          onClick={() => setSource("text")}
        >
          {t(lang, "ar_source_text")}
        </button>
        <button
          role="tab"
          aria-selected={source === "corpus"}
          type="button"
          className={clsx("ar-source-btn", { active: source === "corpus" })}
          onClick={() => setSource("corpus")}
        >
          {t(lang, "ar_source_corpus")}
        </button>
      </div>

      {source === "corpus" ? (
        <div className="ar-corpus-panel">
          <div className="grounding-notice">{t(lang, "ar_corpus_note")}</div>

          {arabicCorpora.length > 0 ? (
            <label className="dialect-picker ar-corpus-picker">
              {t(lang, "ar_corpus_pick")}:
              <select
                value={corpusId}
                onChange={(e) => setCorpusId(e.target.value)}
                disabled={bulkBusy}
              >
                {arabicCorpora.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} · {(c.stats?.token_count ?? 0).toLocaleString()} {t(lang, "ar_corpus_tokens")}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="ar-corpus-empty">
              <div>{t(lang, "ar_corpus_none_hint")}</div>
              <button
                className="run-btn"
                type="button"
                onClick={() => setActiveNav("corpus-target")}
              >
                {t(lang, "ar_corpus_goto")}
              </button>
            </div>
          )}

          {arabicCorpora.length > 0 && (
            <div className="ar-bulk-controls">
              <button onClick={onRunCorpus} disabled={!corpusId || bulkBusy} className="run-btn">
                {bulkBusy
                  ? t(lang, "ar_corpus_analyzing").replace("{n}", String(bulkSt?.elapsed_s ?? 0))
                  : t(lang, "ar_corpus_run")}
              </button>
              {bulkBusy && (
                <button
                  onClick={() => cancelBulk.mutate()}
                  className="run-btn run-btn-cancel"
                  type="button"
                >
                  {t(lang, "ar_cancel")}
                </button>
              )}
            </div>
          )}

          {bulkBusy && bulkSt && (
            <div className="ar-bulk-progress-wrap" role="status">
              <progress className="ar-bulk-progress" value={bulkPct} max={100} />
              <div className="ar-bulk-progress-text">
                {fillVars(t(lang, "ar_corpus_progress"), {
                  done: (bulkSt.tokens_done ?? 0).toLocaleString(),
                  total: (bulkSt.tokens_total ?? 0).toLocaleString(),
                  c: String(bulkSt.chunks_done ?? 0),
                  n: String(bulkSt.chunks_total ?? 0),
                })}
                {bulkSt.eta_s != null
                  ? ` · ${fillVars(t(lang, "ar_corpus_eta"), { n: String(Math.round(bulkSt.eta_s)) })}`
                  : ""}
              </div>
            </div>
          )}

          {startBulk.isError && <ArabicError error={startBulk.error} />}
          {bulkSt?.state === "error" && (
            <div className="error" role="alert">Error: {bulkSt.error}</div>
          )}
          {bulkSt?.state === "cancelled" && (
            <div className="result-meta">{t(lang, "ar_corpus_cancelled")}</div>
          )}

          {bulkSt?.state === "done" && bulkResult.data && (
            <ArabicBulkResultPanel
              result={bulkResult.data}
              source={bulkSt.source ?? null}
              lang={lang}
              exportStatus={exportStatus}
            />
          )}
        </div>
      ) : (
        <>
          {/* Tool selector */}
          <div className="arabic-toolbar">
        <div className="tool-tabs">
          {TOOLS.map((t) => (
            <button
              key={t.id}
              className={clsx("tool-tab", { active: tool === t.id })}
              onClick={() => setTool(t.id)}
            >
              {t.label}
              <span className="arabic-label" dir="rtl">{t.arabicLabel}</span>
            </button>
          ))}
        </div>

        {/* Dialect + tagset pickers for morphology tool */}
        {(tool === "morphology") && (
          <>
            <label className="dialect-picker">
              Dialect DB:
              <select value={dialect} onChange={(e) => setDialect(e.target.value as typeof dialect)}>
                {DIALECT_DBS.map((d) => {
                  const missing = morphDbs ? morphDbs[d.id] === false : false;
                  return (
                    <option key={d.id} value={d.id} disabled={missing}>
                      {d.label}
                      {missing ? ` ${t(lang, "ar_dialect_db_missing")}` : ""}
                    </option>
                  );
                })}
              </select>
            </label>
            <label className="dialect-picker">
              Tagset:
              <select value={tagset} onChange={(e) => setTagset(e.target.value as typeof tagset)} title="Tagset used for the POS column">
                <option value="calima">CAMeL native (calima)</option>
                <option value="upos">UD UPOS (universal)</option>
              </select>
            </label>
          </>
        )}
      </div>

      {/* Text input */}
      <div className="text-input-area">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          dir="rtl"
          lang="ar"
          placeholder="اكتب النص العربي هنا…"
          rows={3}
          className="arabic-textarea"
        />
        <div className="sample-texts">
          Sample texts:
          {SAMPLE_TEXTS.map((s, i) => (
            <button key={i} className="sample-btn" onClick={() => setText(s)} dir="rtl">
              {s.slice(0, 40)}…
            </button>
          ))}
        </div>
        <button onClick={onRun} disabled={!text.trim() || busy} className="run-btn">
          {busy ? t(lang, "ar_analyzing_elapsed").replace("{n}", String(elapsed)) : "Run analysis"}
        </button>
        {busy && (
          <button onClick={onCancel} className="run-btn run-btn-cancel" type="button">
            {t(lang, "ar_cancel")}
          </button>
        )}
        {busy && elapsed >= 10 && (
          <div className="error" role="status">{t(lang, "ar_still_working_hint")}</div>
        )}
      </div>

      {/* Result */}
      {/* v1.2.13-1: Export above every tool result — the table tools export
          their on-screen columns, the text tools a two-column original/result
          pair, the distribution tools a probability table. */}
      {result.data && (
        <div className="result-export-bar arabic-export-bar">
          <ExportButton
            label={t(lang, "analysis_export")}
            formats={["xlsx", "csv", "tsv", "txt", "json"]}
            onExport={(fmt) => {
              if (!result.data) return;
              const { headers, rows } = arabicResultToTable(result.data);
              void downloadTable(headers, rows, `arabic_${submitted?.tool ?? "tools"}.${fmt}`, exportStatus.set);
            }}
          />
          {exportStatus.el}
        </div>
      )}
      {result.data && <ArabicResult result={result.data} />}

          {result.isError && <ArabicError error={result.error} />}
        </>
      )}
    </div>
  );
}


function ArabicResult({ result }: { result: any }) {
  switch (result.kind) {
    case "morphology":
      return (
        <div className="result-block">
          <div className="result-meta">
            Backend: <strong>{result.data.backend}</strong> ·
            Dialect: <strong>{result.data.detected_dialect}</strong> ·
            Tokens: <strong>{result.data.token_count}</strong>
          </div>
          <table className="data-table arabic-table">
            <thead>
              <tr>
                <th>Token</th>
                <th>Root (الجذر)</th>
                <th>Pattern (الوزن)</th>
                <th>Lemma</th>
                <th>POS</th>
                <th>Stem</th>
                <th>Buckwalter</th>
              </tr>
            </thead>
            <tbody>
              {result.data.tokens.map((t: any, i: number) => (
                <tr key={i}>
                  <td dir="rtl" lang="ar" className="arabic-cell">{t.text}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell root-cell">{t.root || "-"}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell pattern-cell">{t.pattern || "-"}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell">{t.lemma || "-"}</td>
                  <td><span className={posClass(t.pos)}>{t.pos}</span></td>
                  <td dir="rtl" lang="ar" className="arabic-cell">{t.stem || "-"}</td>
                  <td className="buckwalter-cell">{t.buckwalter}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "roots":
      return (
        <div className="result-block">
          <h3>Roots (الجذور)</h3>
          <table className="data-table arabic-table">
            <thead>
              <tr>
                <th>Token</th>
                <th>Root (الجذر)</th>
                <th>Pattern (الوزن)</th>
                <th>Lemma</th>
                <th>POS</th>
              </tr>
            </thead>
            <tbody>
              {result.data.roots.map((r: any, i: number) => (
                <tr key={i}>
                  <td dir="rtl" lang="ar" className="arabic-cell">{r.token}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell root-cell">{r.root || "-"}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell pattern-cell">{r.pattern || "-"}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell">{r.lemma}</td>
                  <td><span className="pos-tag pos-other">{r.pos}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "clitics":
      return (
        <div className="result-block">
          <h3>Clitic segmentation</h3>
          <table className="data-table">
            <thead>
              <tr><th>Surface</th><th>Stem</th><th>POS</th></tr>
            </thead>
            <tbody>
              {result.data.segments.map((s: any, i: number) => (
                <tr key={i}>
                  <td dir="rtl" lang="ar" className="arabic-cell">{s.surface}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell">{s.stem}</td>
                  <td><span className="pos-tag pos-other">{s.pos}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "buckwalter":
      return (
        <div className="result-block">
          <h3>Buckwalter transliteration</h3>
          <div className="buckwalter-result">{result.data.buckwalter}</div>
          <div className="original-text" dir="rtl" lang="ar">Original: {result.data.original}</div>
        </div>
      );

    case "dediac":
      return (
        <div className="result-block">
          <h3>Dediacritized</h3>
          <div className="arabic-result" dir="rtl" lang="ar">{result.data.dediacritized}</div>
          <div className="original-text" dir="rtl" lang="ar">Original: {result.data.original}</div>
        </div>
      );

    case "normalize":
      return (
        <div className="result-block">
          <h3>Normalized</h3>
          <div className="arabic-result" dir="rtl" lang="ar">{result.data.normalized}</div>
          <div className="original-text" dir="rtl" lang="ar">Original: {result.data.original}</div>
        </div>
      );

    case "dialect":
      return (
        <div className="result-block">
          <h3>Dialect identification</h3>
          <div className="distribution-bars">
            {Object.entries(result.data.dialect_distribution)
              .sort(([, a]: any, [, b]: any) => Number(b) - Number(a))
              .map(([d, p]: any) => (
                <div key={d} className="bar-row">
                  <span className="bar-label">{d.toUpperCase()}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${p * 100}%`, background: "var(--bar-brand)" }} />
                  </div>
                  <span className="bar-value">{(p * 100).toFixed(1)}%</span>
                </div>
              ))}
          </div>
        </div>
      );

    case "register":
      return (
        <div className="result-block">
          <h3>Register detection</h3>
          <div className="distribution-bars">
            {Object.entries(result.data.register_distribution)
              .sort(([, a]: any, [, b]: any) => Number(b) - Number(a))
              .map(([r, p]: any) => (
                <div key={r} className="bar-row">
                  <span className="bar-label">{r}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${p * 100}%`, background: "var(--bar-accent)" }} />
                  </div>
                  <span className="bar-value">{(p * 100).toFixed(1)}%</span>
                </div>
              ))}
          </div>
        </div>
      );

    case "translate":
      return (
        <div className="result-block">
          <h3>Translation equivalents</h3>
          <div className="result-meta">
            Word: <strong dir="rtl" lang="ar">{result.data.word}</strong> ·
            Direction: <strong>{result.data.direction}</strong> ·
            Source: <code>{result.data.source}</code>
          </div>
          {result.data.equivalents.length > 0 ? (
            <ul className="translation-list">
              {result.data.equivalents.map((eq: string, i: number) => (
                <li key={i} className="translation-item">{eq}</li>
              ))}
            </ul>
          ) : (
            <div className="empty-state">No translation found in the starter dictionary.
              Phase 4 will integrate a proper bilingual word-alignment model.</div>
          )}
        </div>
      );

    default:
      return null;
  }
}

// --------------------------------------------------------------------------- //
// r4: corpus mode — aggregated full-corpus report (kind: arabic_bulk_analysis)
// --------------------------------------------------------------------------- //

/**
 * The bulk job's aggregated report: summary + POS distribution + top-50
 * tables for roots / patterns / lemmas / tokens. The standard export bar
 * (long-format table, shared with every other Arabic tool) sits above the
 * result; a second button downloads the engine's full-depth JSON report
 * (up to 10k entries per table) for archival analysis.
 */
function ArabicBulkResultPanel({
  result,
  source,
  lang,
  exportStatus,
}: {
  result: ArabicBulkResult;
  source: string | null;
  lang: "en" | "ar";
  exportStatus: ReturnType<typeof useExportStatus>;
}) {
  const TOP_N = 50;
  const num = (n: number) => n.toLocaleString();

  const onDownloadJson = async () => {
    try {
      const blob = await api.arabicBulkResultFile();
      const dl = await downloadBlob(blob, "corpusmind-arabic-bulk-analysis.json");
      exportStatus.set(
        dl.ok ? t(lang, "ar_corpus_download_done") : dl.message,
        dl.ok ? "success" : "error",
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      exportStatus.set(fillVars(t(lang, "ar_corpus_download_failed"), { error: msg }), "error");
    }
  };

  const totalTokens = result.token_count || 1;
  const tables: { title: string; itemHeader: string; rows: [string, number][] }[] = [
    { title: t(lang, "ar_corpus_top_roots"), itemHeader: "Root (الجذر)", rows: result.top_roots ?? [] },
    { title: t(lang, "ar_corpus_top_patterns"), itemHeader: "Pattern (الوزن)", rows: result.top_patterns ?? [] },
    { title: t(lang, "ar_corpus_top_lemmas"), itemHeader: "Lemma", rows: result.top_lemmas ?? [] },
    { title: t(lang, "ar_corpus_top_tokens"), itemHeader: "Token", rows: result.top_tokens ?? [] },
  ];

  return (
    <>
      <div className="result-export-bar arabic-export-bar">
        <ExportButton
          label={t(lang, "analysis_export")}
          formats={["xlsx", "csv", "tsv", "txt", "json"]}
          onExport={(fmt) => {
            const { headers, rows } = arabicResultToTable({ kind: "arabic_bulk_analysis", data: result });
            void downloadTable(headers, rows, `arabic_corpus_bulk.${fmt}`, exportStatus.set);
          }}
        />
        <button className="run-btn ar-json-btn" type="button" onClick={() => void onDownloadJson()}>
          {t(lang, "ar_corpus_download_json")}
        </button>
        {exportStatus.el}
      </div>

      <div className="result-block">
        <h3>{t(lang, "ar_corpus_done")}</h3>
        <div className="result-meta">
          {source && (
            <span>
              Source: <strong>{source}</strong> ·{" "}
            </span>
          )}
          {fillVars(t(lang, "ar_corpus_summary"), {
            tokens: num(result.token_count),
            unique: num(result.unique_tokens),
            plurals: num(result.broken_plural_count),
            chunks: num(result.chunks),
          })}
        </div>
      </div>

      <div className="result-block">
        <h3>{t(lang, "ar_corpus_pos")}</h3>
        <div className="distribution-bars">
          {Object.entries(result.pos_distribution ?? {})
            .sort(([, a], [, b]) => b - a)
            .map(([pos, n]) => (
              <div key={pos} className="bar-row">
                <span className="bar-label">{pos}</span>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{ width: `${(n / totalTokens) * 100}%`, background: "var(--bar-brand)" }}
                  />
                </div>
                <span className="bar-value">{num(n)}</span>
              </div>
            ))}
        </div>
      </div>

      {tables.map((tb) => (
        <div className="result-block" key={tb.title}>
          <h3>{tb.title}</h3>
          <table className="data-table arabic-table">
            <thead>
              <tr>
                <th>#</th>
                <th>{tb.itemHeader}</th>
                <th>Frequency</th>
              </tr>
            </thead>
            <tbody>
              {tb.rows.slice(0, TOP_N).map(([item, count], i) => (
                <tr key={`${item}-${i}`}>
                  <td>{i + 1}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell">
                    {item}
                  </td>
                  <td>{num(count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}
