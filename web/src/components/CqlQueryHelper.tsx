/**
 * CqlQueryHelper — the CQL query assistant (v1.2.13-2).
 *
 * Three things, deliberately lightweight and RTL-safe (everything renders
 * BELOW the input, never overlaid on it):
 *   1. example chips that insert a ready-made pattern into the query box;
 *   2. an expandable syntax panel that doubles as the honest
 *      "Differences from CQP" note (no Sketch-Engine/CWB compat claim);
 *   3. an error caret line: when the engine's 422 says "position N: …",
 *      the query is re-printed with a caret pointing at column N
 *      (Arabic/RTL queries render LTR in the monospace preview with
 *      dir="ltr" so column alignment stays meaningful).
 */
import { useState } from "react";
import { t, type Lang } from "@/lib/i18n";

const EXAMPLES: string[] = [
  '"fox"',
  '[lemma="take"] []{0,3} "risk"',
  '[pos="ADJ"] [pos="NOUN"]',
  '[word="book" & pos="NOUN"]',
  '("dog" | "fox") "barked"',
  '"the" []* "of" within sentence',
  '[root="ك.ت.ب"]',
  '[morph="*Animacy=Anim*"]',
];

const SYNTAX_ROWS: Array<[string, string]> = [
  ['"literal"', 'word token; wildcards * (any run) and ? (one char)'],
  ["[attr=\"value\"]", "attribute test: word, lemma, pos, xpos, rel, morph, root, pattern"],
  ["[]", "any single token"],
  ["[]{m,n}", "gap of m..n tokens; also ? * +"],
  ["(a | b)", "group with alternation"],
  ["%c  %d", "ignore case (Unicode folding) / fold diacritics"],
  ["within sentence", "or 'within s' / 'within document' (default)"],
];

const CQP_DIFFS: Array<[string, string]> = [
  ["Quoted values", "wildcards here — in CQP they are regexes (opt-in via cqp_compat)"],
  ["Regex", "only via /re/, unanchored re.search — CQP anchors to the whole token"],
  ["Flags", "%c/%d accepted inside AND after brackets"],
  ["Scope", "within sentence|document only; no structural tags"],
  ["morph", "whole-string match — use *…* for substring"],
  ["Roots/patterns", "real CAMeL format: root=\"ك.ت.ب\", pattern=\"1ُ2ُ3\""],
  ["Turkish İ/ı", "not fold-equivalent to i (consistent in both layers)"],
];

interface CqlQueryHelperProps {
  lang: Lang;
  query: string;
  errorDetail: string | null;
  errorPos: number | null;
}

export function CqlQueryHelper({ lang, query, errorDetail, errorPos }: CqlQueryHelperProps) {
  const [open, setOpen] = useState(false);
  const showCaret = errorDetail != null && errorPos != null && errorPos <= query.length;

  return (
    <div className="cql-hint" data-testid="cql-query-helper">
      <div className="cql-examples" style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        <span style={{ fontSize: 12, color: "var(--text-subtle)" }}>{t(lang, "cql_examples_label")}</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            className="pos-tag pos-other"
            style={{ cursor: "pointer", fontSize: 12 }}
            onClick={() => {
              const ev = new CustomEvent("cql-example", { detail: ex });
              document.dispatchEvent(ev);
            }}
            title={t(lang, "cql_example_insert")}
          >
            {ex}
          </button>
        ))}
        <button
          type="button"
          className="btn-small"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          {open ? t(lang, "cql_syntax_hide") : t(lang, "cql_syntax_show")}
        </button>
      </div>

      {open && (
        <div className="cql-syntax-panel" style={{ marginTop: "var(--space-2)", fontSize: 13 }}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <tbody>
              {SYNTAX_ROWS.map(([pat, desc]) => (
                <tr key={pat}>
                  <td style={{ padding: "2px 8px 2px 0", whiteSpace: "nowrap" }}><code>{pat}</code></td>
                  <td style={{ padding: "2px 0", color: "var(--text-subtle)" }}>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 8, fontWeight: 600 }}>{t(lang, "cql_diffs_title")}</div>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <tbody>
              {CQP_DIFFS.map(([what, how]) => (
                <tr key={what}>
                  <td style={{ padding: "2px 8px 2px 0", whiteSpace: "nowrap" }}>{what}</td>
                  <td style={{ padding: "2px 0", color: "var(--text-subtle)" }}>{how}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCaret && (
        <pre
          data-testid="cql-error-caret"
          dir="ltr"
          style={{
            marginTop: "var(--space-2)",
            fontFamily: "var(--font-mono, monospace)",
            fontSize: 13,
            whiteSpace: "pre-wrap",
            color: "var(--danger, #b3261e)",
          }}
        >
          {query + "\n" + " ".repeat(errorPos!) + "^ " + t(lang, "cql_error_here")}
        </pre>
      )}
    </div>
  );
}
