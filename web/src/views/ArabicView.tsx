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
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";
import { ArabicDataPackCard } from "@/components/ArabicDataPackCard";

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

  const backends = useQuery({ queryKey: ["arabic-backends"], queryFn: ({ signal }) => api.arabicBackends(signal) });

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

  // v1.2.11 (Arabic Tools hang fix): elapsed-seconds ticker while a request
  // is in flight, so "Analyzing…" never looks like a silent freeze again.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!result.isPending || !submitted) {
      setElapsed(0);
      return;
    }
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [result.isPending, submitted]);

  const onCancel = () => {
    void queryClient.cancelQueries({ queryKey: ["arabic", submitted] });
  };

  const onRun = () => {
    if (!text.trim()) return;
    setSubmitted({ text: text.trim(), tool, dialect, tagset });
  };

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
                <option value="msa">MSA (calima-msa-r13)</option>
                <option value="egy">Egyptian (calima-egy-r13)</option>
                <option value="glf">Gulf (calima-glf-01)</option>
                <option value="lev">Levantine (calima-lev-01)</option>
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
        <button onClick={onRun} disabled={!text.trim() || result.isPending} className="run-btn">
          {result.isPending ? t(lang, "ar_analyzing_elapsed").replace("{n}", String(elapsed)) : "Run analysis"}
        </button>
        {result.isPending && (
          <button onClick={onCancel} className="run-btn run-btn-cancel" type="button">
            {t(lang, "ar_cancel")}
          </button>
        )}
        {result.isPending && elapsed >= 10 && (
          <div className="error" role="status">{t(lang, "ar_still_working_hint")}</div>
        )}
      </div>

      {/* Result */}
      {result.data && <ArabicResult result={result.data} />}

      {result.isError && <ArabicError error={result.error} />}
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
