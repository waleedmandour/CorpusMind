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
 * v1.2.13-1: Simple | CQL mode toggle (CQL-lite: token sequences with
 * attributes, gaps, alternation, within scoping).
 * v1.2.13-2 hardening round:
 * - CQL requests carry react-query's AbortSignal + a 60 s client deadline;
 *   a visible Cancel button + elapsed-seconds ticker (mirrors ArabicView).
 * - The stale-seed bug is fixed (the seed used for the request is computed
 *   locally, not read back from state).
 * - ONE shared KWIC table (components/KwicTable.tsx) for both modes — the
 *   two byte-identical copies could drift.
 * - CQL mode exports SERVER-SIDE (the engine re-runs the query; the export
 *   covers the full match set, not just the fetched page).
 * - Student gating: when the server rejects CQL with 403 (older engine or
 *   future policy), the CQL toggle hides and the view falls back to Simple
 *   with a visible notice instead of a dead button.
 * - Query helper: example chips, an error caret under the offending
 *   position, and an expandable syntax panel ( Differences from CQP).
 */
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api, exportWithFeedback, type ExportFormat, type ConcordanceSortSpec } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";
import { SlowQueryNote } from "@/components/SlowQueryNote";
import { ExportButton } from "@/components/ExportButton";
import { KwicTable, KwicPagination } from "@/components/KwicTable";
import { CqlQueryHelper } from "@/components/CqlQueryHelper";

const LEVELS = ["word", "lemma", "pos", "root", "pattern"] as const;
const PAGE_SIZE = 200;

// v1.2.13-1: the engine wraps every HTTP failure as `HTTP <status>: <body>`;
// FastAPI body is {"detail": …}. Unwrap it so a CQL syntax error shows the
// position-annotated message ("Invalid CQL query: …col 12…") instead of raw
// JSON. Same parsing ArabicError has done since v1.2.11.
export function engineErrorDetail(e: unknown): string {
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

// v1.2.13-2: pull the offending character position out of the engine's
// "position N: …" message so the error caret can point at it.
export function cqlErrorPosition(detail: string): number | null {
  const m = /position\s+(\d+)/i.exec(detail);
  return m ? parseInt(m[1], 10) : null;
}

export function ConcordancerView() {
  const cid = useApp((s) => s.activeCorpusId);
  const lang = useUI((s) => s.lang);
  // v1.2.9 student client: the role gates nothing here directly (the engine
  // allowlist decides), but a 403 from the CQL endpoint flips cqlBlocked so
  // the dead toggle is hidden instead of haunting the student.
  const studentClient = useUI((s) => s.studentClient);
  const queryClient = useQueryClient();
  // v1.2.13-1: query mode — Simple (the single-node box) or CQL (token
  // sequences with attributes, gaps, alternation, within scoping; engine
  // endpoint POST /concordance/cql, engine/stats/cql.py documents grammar).
  const [mode, setMode] = useState<"simple" | "cql">("simple");
  const [cqlBlocked, setCqlBlocked] = useState(false);
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
  // sent and the engine had no sampling support. The seed is generated per
  // search, echoed back by the engine in query.sample_seed, and shown in the
  // result metadata so the sample is reproducible. (v1.2.13-2: no separate
  // state — the stale-seed bug came precisely from reading this state back
  // in the same tick; the seed now lives in `submitted` only.)
  const [offset, setOffset] = useState(0);
  const [submitted, setSubmitted] = useState<{ mode: "simple" | "cql"; q: string; l: string; w: number; cs: boolean; rs: boolean; seed: number | null; rx: boolean; sort: ConcordanceSortSpec[]; nm: boolean } | null>(null);
  // Issue 5: visible export status so the user knows what happened
  const [exportStatus, setExportStatus] = useState<{ kind: "success" | "error" | "info"; msg: string } | null>(null);
  // v1.2.13-2: elapsed-seconds ticker while a CQL request is in flight
  // (mirrors the Arabic Tools hang fix — never a silent freeze).
  const [elapsed, setElapsed] = useState(0);

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
    queryFn: ({ signal }) =>
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
          }, signal)
        : api.concordance(cid!, submitted!.q, submitted!.l as any, submitted!.w, PAGE_SIZE, offset, submitted!.cs, submitted!.rs ? 100 : null, submitted!.seed, submitted!.rx, submitted!.sort, submitted!.nm),
    enabled: !!cid && !!submitted,
    // v1.2.13-1: no TanStack-level retry. A CQL syntax error (422) is
    // deterministic — retrying it just delays the same message by the
    // default backoff (the same reasoning as the Arabic Tools hang fix);
    // connection-level restarts are already handled inside jsonFetch.
    retry: false,
  });

  // v1.2.12 lesson (query-pending guard): isPending is true before the first
  // run for enabled-gated queries — "in flight" is isFetching.
  const busy = result.isFetching;

  // v1.2.13-2: elapsed ticker while the request is in flight.
  useEffect(() => {
    if (!busy || !submitted) {
      setElapsed(0);
      return;
    }
    const startedAt = Date.now();
    // NOTE: bare setInterval — the `window` STATE (KWIC size) shadows the
    // global in this component.
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [busy, submitted]);

  const onCancel = () => {
    void queryClient.cancelQueries({ queryKey: ["concordance", cid, submitted] });
  };

  // v1.2.13-2: the query helper's example chips fill the input via this
  // document event (keeps the helper free of view state; document, not the
  // shadowed `window` state).
  useEffect(() => {
    const onExample = (e: Event) => {
      const ex = (e as CustomEvent<string>).detail;
      if (typeof ex === "string" && ex) setQuery(ex);
    };
    document.addEventListener("cql-example", onExample);
    return () => document.removeEventListener("cql-example", onExample);
  }, []);

  const onSearch = () => {
    if (!query.trim()) return;
    setOffset(0);
    // v1.2.13-2 stale-seed fix: the OLD code called setSampleSeed(...) and
    // then read `sampleSeed` back into `submitted` in the same tick — state
    // updates are async, so `submitted.seed` was the PREVIOUS search's seed
    // (or null). Compute the seed locally; it lives only in `submitted`.
    const seed = randomSample ? Math.floor(Math.random() * 1_000_000) : null;
    setSubmitted({ mode, q: query.trim(), l: level, w: window, cs: caseSensitive, rs: randomSample, seed, rx: regex, sort: sortLevels, nm: normalizeArabic });
  };

  // v1.2.13-2: export — BOTH modes are server-side now. Simple keeps the
  // existing endpoint; CQL uses export/concordance/cql (the engine re-runs
  // the query under the matcher guards and streams the full match set).
  // svg/png were never offered for concordance (they are collocation-network
  // diagram formats) — ExportButton's default format list excludes them.
  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!submitted || !cid || !result.data) return;
    setExportStatus(null);
    if (submitted.mode === "cql") {
      await exportWithFeedback(
        () => api.exportConcordanceCql(cid, { query: submitted.q, window: submitted.w, normalize: submitted.nm ? true : null }, fmt as ExportFormat),
        `cql_concordance.${fmt}`,
        (msg, kind) => setExportStatus({ kind, msg }),
      );
      return;
    }
    await exportWithFeedback(
      () => api.exportConcordance(cid, submitted.q, fmt as ExportFormat, submitted.l as any, submitted.w, 1000),
      `concordance_${submitted.q}.${fmt}`,
      (msg, kind) => setExportStatus({ kind, msg }),
    );
  };

  // v1.2.13-2 student gating: a 403 from the CQL endpoint means this server
  // does not admit students to CQL — hide the toggle and fall back to Simple
  // with a visible notice (rather than a button that always errors).
  useEffect(() => {
    if (result.isError && submitted?.mode === "cql") {
      const msg = engineErrorDetail(result.error);
      if (msg.startsWith("HTTP 403") || msg.includes("not available in Student Mode")) {
        setCqlBlocked(true);
        setMode("simple");
      }
    }
  }, [result.isError, result.error, submitted]);

  const total = result.data?.total ?? 0;
  const hasNext = offset + PAGE_SIZE < total;
  const hasPrev = offset > 0;
  const errorDetail = result.isError ? engineErrorDetail(result.error) : null;
  const errorPos = errorDetail ? cqlErrorPosition(errorDetail) : null;

  if (!cid) return <div className="empty-state">Select a corpus to start searching. Go to <strong>Your Corpus</strong> in the sidebar.</div>;

  return (
    <div className="concordancer">
      <div className="search-bar">
        {/* v1.2.13-1: query mode — Simple single-node box or CQL-lite pattern
            (token sequences, gaps, alternation, within sentence|document).
            v1.2.13-2: hidden entirely once the server rejects CQL for this
            role (student gating) instead of showing a dead button. */}
        {!cqlBlocked && (
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
        )}
        {cqlBlocked && studentClient && (
          <div className="cql-hint" role="note">
            {t(lang, "cql_blocked_student")}
          </div>
        )}
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
        <button onClick={onSearch} disabled={!query.trim() || busy}>
          {busy ? t(lang, "ar_analyzing_elapsed").replace("{n}", String(elapsed)) : mode === "cql" ? "Run CQL" : "Search"}
        </button>
        {busy && mode === "cql" && (
          <button onClick={onCancel} className="run-btn run-btn-cancel" type="button" title={t(lang, "cql_cancel_hint")}>
            {t(lang, "ar_cancel")}
          </button>
        )}
        <ExportButton onExport={onExport} disabled={!submitted || !result.data} />
      </div>

      {/* v1.2.13-1: one-line CQL crib shown only in CQL mode.
          v1.2.13-2: replaced by the full query helper (examples, syntax
          panel with the Differences-from-CQP notes, error caret). */}
      {mode === "cql" && (
        <CqlQueryHelper
          lang={lang}
          query={submitted?.q ?? query}
          errorDetail={errorDetail}
          errorPos={errorPos}
        />
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
          detail ("Invalid CQL query: …") instead of a raw HTTP/JSON dump.
          v1.2.13-2: the caret position is rendered by CqlQueryHelper. */}
      {result.isError && (
        <div className="error" role="alert">
          Error: {errorDetail}
        </div>
      )}
      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total.toLocaleString()}</strong> match{result.data.total === 1 ? "" : "es"}
            {submitted?.mode === "cql" ? (
              <>
                {" "}for CQL <code>{String(result.data.query.q)}</code>
                {result.data.query.within ? ` within ${result.data.query.within}` : ""}
              </>
            ) : (
              <>
                {" "}for <code>{String(result.data.query.q)}</code> ({String(result.data.query.level)} level)
                {result.data.query.regex ? " (regex)" : ""}
                {query.trim().includes(" ") && !regex && " (phrase)"}
                {caseSensitive && " (case sensitive)"}
              </>
            )}
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
              {/* v1.2.13-2: ONE shared table for Simple and CQL — the two
                  byte-identical copies could drift. */}
              <KwicTable lines={result.data.lines} corpusLang={corpusLang} corpusScriptTag={corpusScriptTag} />
              <KwicPagination
                total={total}
                offset={offset}
                pageSize={PAGE_SIZE}
                hasPrev={hasPrev}
                hasNext={hasNext}
                isFetching={result.isFetching}
                onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                onNext={() => setOffset(offset + PAGE_SIZE)}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
