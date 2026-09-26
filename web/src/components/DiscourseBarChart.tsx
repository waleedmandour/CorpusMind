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
 * - Compare mode: one diverging bar per category around a zero axis,
 *   length proportional to Log Ratio (Hardie 2014, log2 effect size):
 *   right = more frequent in the target corpus, left = more frequent in
 *   the reference corpus. Categories with an undefined Log Ratio (absent
 *   from one side) are listed separately below the chart.
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

export interface DiscourseChartRow {
  cat: string;
  info: DiscourseCategory;
}

const fmt = (v: number, digits = 1) =>
  v.toLocaleString(undefined, { maximumFractionDigits: digits });

export function DiscourseBarChart({ rows, hasCompare }: { rows: DiscourseChartRow[]; hasCompare: boolean }) {
  const lang = useUI((s) => s.lang);
  if (rows.length === 0) return null;

  if (hasCompare) {
    return <DivergingChart rows={rows} lang={lang} />;
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
                {label}
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
  const LABEL_W = 190;
  const W = 640;
  const ROW_H = 20;
  const H = withLr.length * ROW_H + 26;
  const half = (W - LABEL_W - 16) / 2;
  const midX = LABEL_W + half + 8;

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
              <text x={midX + (positive ? 0 : 0)} y={y + 11} textAnchor="end" className="discourse-chart-label">
                {label}
              </text>
              <rect
                x={positive ? midX + 2 : midX - 2 - w}
                y={y + 2}
                width={w}
                height={ROW_H - 7}
                rx="2"
                fill={positive ? "var(--brand-500)" : "var(--tool6-accent)"}
              />
              <text
                x={positive ? midX + w + 10 : midX - w - 4}
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
          <span className="pi-legend-swatch" style={{ background: "var(--brand-500)" }} />
          {t(lang, "discourse_chart_more_target")}
        </span>
        <span className="pi-legend-item">
          <span className="pi-legend-swatch" style={{ background: "var(--tool6-accent)" }} />
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
