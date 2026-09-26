/**
 * DiscourseBarChart — v1.2.8 (review #3): a visual for the discourse
 * statistics table, plotting exactly the columns the table already
 * computes (no new metric):
 *
 * - Single-corpus mode: one horizontal bar per category, length
 *   proportional to its per-million rate (falling back to the raw
 *   frequency for lenses that report an index instead, e.g. persuasion,
 *   which uses the radar instead of this chart). Bars are colored by the
 *   taxonomy's discourse group when the engine provides one.
 * - Compare mode (v1.2.9): TWO views, both requested in review round 3:
 *   1. Grouped target-vs-reference bars (green = target, purple =
 *      reference) on the shared per-million scale — the "which corpus
 *      uses more of what" picture;
 *   2. The diverging Log-Ratio bars around a zero axis (green = more
 *      frequent in the target, red = more frequent in the reference) —
 *      the effect-size picture. Each category label sits on the OPPOSITE
 *      side of its bar's direction (bar right -> text left, and vice
 *      versa) so a growing bar can never paint over its own text.
 *   Categories with an undefined Log Ratio (absent from one side) are
 *   listed separately below the divergence chart.
 *
 * Comparison palette (v1.2.9, applies app-wide): target = green
 * (--bar-positive), reference = purple (--tool5-accent); divergence =
 * green/red (--bar-positive/--bar-negative). All theme-aware.
 *
 * Pure inline SVG, no chart dependency — consistent with the repo's
 * offline-first PWA stance and the PersuasionRadar approach.
 */
import type { DiscourseCategory } from "@/lib/api";
import { useUI } from "@/store/ui";
import { t, type Lang } from "@/lib/i18n";

// Fixed palette (theme tokens) for taxonomy groups; assignment is
// deterministic (sorted group order) so the same group always gets the
// same color within a session and across re-renders.
const GROUP_PALETTE = [
  "var(--tool1-accent)",
  "var(--tool2-accent)",
  "var(--tool3-accent)",
  "var(--tool4-accent)",
  "var(--tool5-accent)",
  "var(--tool6-accent)",
  "var(--tool7-accent)",
  "var(--tool8-accent)",
];

// v1.2.9 comparison palette — target vs reference and divergence colors
// shared by every comparison visual (Discourse grouped + diverging bars,
// Keyness effect-size chips). Theme-aware tokens, tuned for WCAG contrast
// in both light and dark themes (see global.css --bar-* tokens).
export const COMPARE_TARGET_COLOR = "var(--bar-positive)"; // green
export const COMPARE_REFERENCE_COLOR = "var(--tool5-accent)"; // purple
export const COMPARE_DIVERGE_POS = "var(--bar-positive)"; // green: target over-use
export const COMPARE_DIVERGE_NEG = "var(--bar-negative)"; // red: reference over-use

export interface DiscourseChartRow {
  cat: string;
  info: DiscourseCategory;
}

const fmt = (v: number, digits = 1) =>
  v.toLocaleString(undefined, { maximumFractionDigits: digits });

// Category keys can be long ("transitivity.material", USAS group names);
// overlong labels would overflow the SVG viewBox and get clipped, which
// reads as broken data. Truncate with an ellipsis and keep the full text
// as a hover <title> (v1.2.8 review #4).
const truncateLabel = (s: string, max: number) =>
  s.length > max ? s.slice(0, Math.max(1, max - 1)) + "\u2026" : s;

export function DiscourseBarChart({ rows, hasCompare }: { rows: DiscourseChartRow[]; hasCompare: boolean }) {
  const lang = useUI((s) => s.lang);
  if (rows.length === 0) return null;

  if (hasCompare) {
    return (
      <>
        <GroupedCompareChart rows={rows} lang={lang} />
        <DivergingChart rows={rows} lang={lang} />
      </>
    );
  }
  return <SingleCorpusChart rows={rows} lang={lang} />;
}

function SingleCorpusChart({ rows, lang }: { rows: DiscourseChartRow[]; lang: Lang }) {
  // Value priority: per-million rate when the lens reports one; otherwise
  // the raw freq column (which for index lenses is the 0-100 index).
  const valued = rows
    .map((r) => ({
      cat: r.cat,
      group: r.info.group ?? "",
      value: r.info.per_million ?? Number(r.info.freq ?? 0),
      isRate: r.info.per_million != null,
    }))
    .filter((r) => Number.isFinite(r.value));
  if (valued.length === 0) return null;

  const max = Math.max(...valued.map((r) => r.value), 0.000001);
  const groups = [...new Set(valued.map((r) => r.group))].sort();
  const groupColor = new Map(groups.map((g, i) => [g, GROUP_PALETTE[i % GROUP_PALETTE.length]]));

  const LABEL_W = 190;
  const VALUE_W = 70;
  const ROW_H = 20;
  const W = 640;
  const H = valued.length * ROW_H + 26;
  const barMax = W - LABEL_W - VALUE_W;

  return (
    <figure className="discourse-chart-wrap">
      <figcaption className="discourse-chart-title">
        {t(lang, valued[0].isRate ? "discourse_chart_title_pm" : "discourse_chart_title_freq")}
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={t(lang, "discourse_chart_title_freq")}
      >
        {valued.map((r, i) => {
          const y = i * ROW_H + 20;
          const w = Math.max(1.5, (r.value / max) * barMax);
          const label = r.cat.startsWith("pi.") ? r.cat.split(".").slice(2).join(".") : r.cat;
          return (
            <g key={r.cat}>
              <text x={LABEL_W - 8} y={y + 11} textAnchor="end" className="discourse-chart-label">
                <title>{label}</title>
                {truncateLabel(label, 30)}
              </text>
              <rect
                x={LABEL_W}
                y={y + 2}
                width={w}
                height={ROW_H - 7}
                rx="2"
                fill={groupColor.get(r.group) ?? "var(--brand-500)"}
              />
              <text x={LABEL_W + w + 6} y={y + 11} className="discourse-chart-value">
                {fmt(r.value, r.isRate ? 1 : 1)}
              </text>
            </g>
          );
        })}
      </svg>
      {groups.filter(Boolean).length > 1 && (
        <div className="discourse-chart-legend">
          {groups.filter(Boolean).map((g) => (
            <span key={g} className="pi-legend-item">
              <span className="pi-legend-swatch" style={{ background: groupColor.get(g) }} />
              {g}
            </span>
          ))}
        </div>
      )}
    </figure>
  );
}

/**
 * v1.2.9: grouped target-vs-reference bars on the shared per-million
 * scale. Green = target corpus, purple = reference corpus. Falls back to
 * null when the engine didn't send reference rates (pre-1.2.9 response).
 */
function GroupedCompareChart({ rows, lang }: { rows: DiscourseChartRow[]; lang: Lang }) {
  const valued = rows
    .map((r) => ({
      cat: r.cat,
      target: r.info.per_million ?? 0,
      reference: r.info.ref_per_million,
      hasRef: r.info.ref_per_million != null && Number.isFinite(r.info.ref_per_million),
    }))
    .filter((r) => r.hasRef && Number.isFinite(r.target));
  if (valued.length === 0) return null;

  const max = Math.max(...valued.flatMap((r) => [r.target, r.reference ?? 0]), 0.000001);

  const LABEL_W = 190;
  const VALUE_W = 64;
  const ROW_H = 24;
  const W = 640;
  const H = valued.length * ROW_H + 26;
  const barMax = W - LABEL_W - VALUE_W;
  const BAR_H = 6;

  return (
    <figure className="discourse-chart-wrap">
      <figcaption className="discourse-chart-title">
        {t(lang, "discourse_chart_title_grouped")}
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={t(lang, "discourse_chart_title_grouped")}
      >
        {valued.map((r, i) => {
          const y = i * ROW_H + 20;
          const wT = Math.max(1.5, ((r.target ?? 0) / max) * barMax);
          const wR = Math.max(1.5, ((r.reference ?? 0) / max) * barMax);
          const label = r.cat.startsWith("pi.") ? r.cat.split(".").slice(2).join(".") : r.cat;
          return (
            <g key={r.cat}>
              <text x={LABEL_W - 8} y={y + 11} textAnchor="end" className="discourse-chart-label">
                <title>{label}</title>
                {truncateLabel(label, 30)}
              </text>
              {/* target bar (green) — top of the pair */}
              <rect
                x={LABEL_W}
                y={y}
                width={wT}
                height={BAR_H}
                rx="2"
                fill={COMPARE_TARGET_COLOR}
              >
                <title>{`${label} — ${t(lang, "discourse_chart_target")}: ${fmt(r.target)}`}</title>
              </rect>
              {/* reference bar (purple) — bottom of the pair */}
              <rect
                x={LABEL_W}
                y={y + BAR_H + 2}
                width={wR}
                height={BAR_H}
                rx="2"
                fill={COMPARE_REFERENCE_COLOR}
              >
                <title>{`${label} — ${t(lang, "discourse_chart_reference")}: ${fmt(r.reference ?? 0)}`}</title>
              </rect>
              <text x={LABEL_W + Math.max(wT, wR) + 6} y={y + 12} className="discourse-chart-value">
                {fmt(r.target)}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="discourse-chart-legend">
        <span className="pi-legend-item">
          <span className="pi-legend-swatch" style={{ background: COMPARE_TARGET_COLOR }} />
          {t(lang, "discourse_chart_target")}
        </span>
        <span className="pi-legend-item">
          <span className="pi-legend-swatch" style={{ background: COMPARE_REFERENCE_COLOR }} />
          {t(lang, "discourse_chart_reference")}
        </span>
      </div>
    </figure>
  );
}

function DivergingChart({ rows, lang }: { rows: DiscourseChartRow[]; lang: Lang }) {
  const withLr = rows
    .map((r) => ({ cat: r.cat, lr: r.info.log_ratio ?? null }))
    .filter((r): r is { cat: string; lr: number } => r.lr != null && Number.isFinite(r.lr))
    .sort((a, b) => b.lr - a.lr);
  const skipped = rows.filter(
    (r) => r.info.log_ratio == null || !Number.isFinite(r.info.log_ratio),
  );
  if (withLr.length === 0) return null;

  const maxAbs = Math.max(...withLr.map((r) => Math.abs(r.lr)), 0.000001);
  // Compare-mode geometry (v1.2.8 review #4): there is no fixed label
  // column. Each row's label sits on the OPPOSITE side of its bar's
  // direction (bar right -> label left of the zero axis, bar left ->
  // label right of it), so a growing bar can never paint over its own
  // text. The reserved 60px per side holds the numeric value at the bar
  // tip without clipping at the viewBox edge.
  const W = 640;
  const ROW_H = 20;
  const H = withLr.length * ROW_H + 26;
  const half = W / 2 - 60;
  const midX = W / 2;

  return (
    <figure className="discourse-chart-wrap">
      <figcaption className="discourse-chart-title">
        {t(lang, "discourse_chart_title_lr")}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={t(lang, "discourse_chart_title_lr")}>
        <line x1={midX} y1={4} x2={midX} y2={H - 8} stroke="var(--border-strong)" strokeWidth="1" />
        {withLr.map((r, i) => {
          const y = i * ROW_H + 20;
          const w = Math.max(1.5, (Math.abs(r.lr) / maxAbs) * half);
          const positive = r.lr >= 0;
          const label = r.cat.startsWith("pi.") ? r.cat.split(".").slice(2).join(".") : r.cat;
          return (
            <g key={r.cat}>
              <text
                x={positive ? midX - 6 : midX + 6}
                y={y + 11}
                textAnchor={positive ? "end" : "start"}
                className="discourse-chart-label"
              >
                <title>{label}</title>
                {truncateLabel(label, 34)}
              </text>
              {/* v1.2.9: divergence palette — green = target over-use,
                  red = reference over-use (was green/teal). */}
              <rect
                x={positive ? midX + 2 : midX - 2 - w}
                y={y + 2}
                width={w}
                height={ROW_H - 7}
                rx="2"
                fill={positive ? COMPARE_DIVERGE_POS : COMPARE_DIVERGE_NEG}
              />
              <text
                x={positive ? midX + w + 10 : midX - w - 10}
                y={y + 11}
                textAnchor={positive ? "start" : "end"}
                className="discourse-chart-value"
              >
                {fmt(r.lr, 2)}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="discourse-chart-legend">
        <span className="pi-legend-item">
          <span className="pi-legend-swatch" style={{ background: COMPARE_DIVERGE_POS }} />
          {t(lang, "discourse_chart_more_target")}
        </span>
        <span className="pi-legend-item">
          <span className="pi-legend-swatch" style={{ background: COMPARE_DIVERGE_NEG }} />
          {t(lang, "discourse_chart_more_reference")}
        </span>
      </div>
      {skipped.length > 0 && (
        <div className="cat-meta">
          {t(lang, "discourse_chart_skipped").replace("{n}", String(skipped.length))}
        </div>
      )}
    </figure>
  );
}
