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
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api } from "@/lib/api";

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

export function ArabicView() {
  const [text, setText] = useState(SAMPLE_TEXTS[0]);
  const [tool, setTool] = useState<Tool>("morphology");
  const [dialect, setDialect] = useState<"msa" | "egy" | "glf" | "lev">("msa");
  const [submitted, setSubmitted] = useState<{ text: string; tool: Tool; dialect: string } | null>(null);

  const backends = useQuery({ queryKey: ["arabic-backends"], queryFn: api.arabicBackends });

  const result = useQuery({
    queryKey: ["arabic", submitted],
    queryFn: async () => {
      if (!submitted) return null;
      const t = submitted.text;
      switch (submitted.tool) {
        case "morphology":
          return { kind: "morphology" as const, data: await api.arabicAnalyze(t, submitted.dialect) };
        case "roots":
          return { kind: "roots" as const, data: await api.arabicRoots(t) };
        case "clitics":
          return { kind: "clitics" as const, data: await api.arabicClitics(t) };
        case "buckwalter":
          return { kind: "buckwalter" as const, data: await api.arabicBuckwalter(t) };
        case "dediac":
          return { kind: "dediac" as const, data: await api.arabicDediacritize(t) };
        case "normalize":
          return { kind: "normalize" as const, data: await api.arabicNormalize(t) };
        case "dialect":
          return { kind: "dialect" as const, data: await api.arabicDialect(t) };
        case "register":
          return { kind: "register" as const, data: await api.arabicRegister(t) };
        case "translate":
          // For translate, we treat the input as a single word
          return { kind: "translate" as const, data: await api.translate(t.trim(), "ar-en") };
      }
    },
    enabled: !!submitted,
  });

  const onRun = () => {
    if (!text.trim()) return;
    setSubmitted({ text: text.trim(), tool, dialect });
  };

  return (
    <div className="arabic-view">
      <div className="grounding-notice">
        <strong>8.21:</strong> Arabic is a first-class citizen, not a bolt-on. Backend: CAMeL Tools
        (calima-msa-r13). Roots (الجذر) and patterns (الوزن) are extracted via the
        SAMA/CALIMA-style morphological analyzer. Farasa and SinaTools are stubbed
        and can be swapped in without touching the rest of the engine.
      </div>

      {/* Backends */}
      {backends.data && (
        <div className="backends-bar">
          {backends.data.backends.map((b) => (
            <span key={b.name} className={clsx("backend-chip", { available: b.available })}>
              {b.name} {b.available ? `✓ (${b.model})` : "— stubbed"}
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

        {/* Dialect picker for morphology tool */}
        {(tool === "morphology") && (
          <label className="dialect-picker">
            Dialect DB:
            <select value={dialect} onChange={(e) => setDialect(e.target.value as typeof dialect)}>
              <option value="msa">MSA (calima-msa-r13)</option>
              <option value="egy">Egyptian (calima-egy-r13)</option>
              <option value="glf">Gulf (calima-glf-01)</option>
              <option value="lev">Levantine (calima-lev-01)</option>
            </select>
          </label>
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
          {result.isPending ? "Analyzing…" : "Run analysis"}
        </button>
      </div>

      {/* Result */}
      {result.data && <ArabicResult result={result.data} />}

      {result.isError && <div className="error">Error: {String(result.error)}</div>}
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
                  <td dir="rtl" lang="ar" className="arabic-cell root-cell">{t.root || "—"}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell pattern-cell">{t.pattern || "—"}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell">{t.lemma || "—"}</td>
                  <td><span className="pos-tag pos-other">{t.pos}</span></td>
                  <td dir="rtl" lang="ar" className="arabic-cell">{t.stem || "—"}</td>
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
                  <td dir="rtl" lang="ar" className="arabic-cell root-cell">{r.root || "—"}</td>
                  <td dir="rtl" lang="ar" className="arabic-cell pattern-cell">{r.pattern || "—"}</td>
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
