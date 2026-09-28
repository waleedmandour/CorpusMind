/**
 * TaxonomyRadar — v1.2.10: generic N-axis radar for the cue-based
 * discourse taxonomies (Hyland 2005, Halliday & Hasan 1976, Martin &
 * White 2005, Cialdini 2007, SFG). The persuasion lens keeps its own
 * PersuasionRadar: PI dimensions are 0-100 package scores, while cue
 * categories are raw frequencies — so here every axis is NORMALIZED to
 * the most frequent category (profile shape, not absolute rates) and the
 * UI renders an explicit hint line saying exactly that.
 *
 * Axis order is alphabetical — the same deterministic order the
 * /discourse/taxonomies endpoint reports — independent of per-corpus
 * frequencies, so two corpora under the same taxonomy produce comparable
 * polygon shapes. Callers gate rendering to 3-12 categories (below 3 a
 * radar is meaningless; above 12 — e.g. the 21 USAS top-level tags — it
 * is unreadable and the bar chart carries the view alone).
 *
 * Pure inline SVG, no chart dependency — consistent with the repo's
 * offline-first PWA stance and the PersuasionRadar conventions.
 */
import { useRef } from "react";

import { ChartExportButton } from "@/components/ChartExportButtons";
import type { DiscourseCategory } from "@/lib/api";

export const RADAR_MIN_AXES = 3;
export const RADAR_MAX_AXES = 12;

export function TaxonomyRadar({
  categories,
  noHitsLabel,
  exportName = "corpusmind-discourse-radar",
}: {
  categories: Record<string, DiscourseCategory>;
  /** Shown instead of a shapeless point-polygon when no category has hits. */
  noHitsLabel?: string;
  /** Download name for the Export PNG button (no extension). */
  exportName?: string;
}) {
  // v1.2.10 field fixes: the radar used to render at a 320-unit viewBox
  // capped at 320px — visibly smaller than the full-width bar chart above
  // it. 420 units with a 780px cap (a further +50% over the first 520px
  // pass), centered, captions below (CSS) — the chart is now the visual
  // peer of the bar chart, not its thumbnail.
  const SIZE = 420;
  const C = SIZE / 2;
  const R = 150;
  const svgRef = useRef<SVGSVGElement | null>(null);
  const RINGS = [25, 50, 75, 100];
  const ACCENT = "var(--tool2-accent)";

  const axes = Object.keys(categories)
    .sort((a, b) => a.localeCompare(b))
    .map((cat) => ({
      cat,
      // Namespace dots and snake_case both become word breaks, so
      // "interactive.transitions" reads as "interactive transitions".
      label: cat.replace(/[_.]/g, " "),
      freq: Math.max(0, Number(categories[cat]?.freq) || 0),
      angle: 0,
    }));
  const max = Math.max(...axes.map((a) => a.freq), 1);
  // v1.2.10 release fix: a corpus with zero cue hits (e.g. the English-only
  // Cialdini lens on an Arabic corpus) used to render a degenerate radar —
  // rings + labels with the polygon collapsed to a single center point,
  // which reads as a chart that is not wired to the data. Render an
  // explicit no-hits note instead of a fake shape.
  const empty = axes.every((a) => a.freq === 0);
  const n = axes.length || 1;
  axes.forEach((a, i) => {
    a.angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
  });

  const pt = (angle: number, radius: number) => ({
    x: C + radius * Math.cos(angle),
    y: C + radius * Math.sin(angle),
  });

  const polygon = axes
    .map((a) => pt(a.angle, (R * a.freq) / max))
    .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");
  const vertices = axes
    .map((a) => pt(a.angle, (R * a.freq) / max))
    .map((p, i) => ({ ...p, key: i }));

  return (
    <div className="taxonomy-radar-wrap">
      <div className="radar-toolbar">
        <ChartExportButton targetRef={svgRef} filename={exportName} />
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        width="100%"
        role="img"
        aria-label={`Category radar, ${n} axes, normalized to the most frequent category`}
      >
        {RINGS.map((r) => (
          <circle key={r} cx={C} cy={C} r={(R * r) / 100} fill="none" stroke="var(--border)" strokeWidth="0.7" />
        ))}
        {axes.map((a, i) => {
          const outer = pt(a.angle, R);
          const labelPos = pt(a.angle, R + 18);
          const title = `${a.label}: ${a.freq.toLocaleString()} (of max ${max.toLocaleString()})`;
          // Compound keys ("commitment consistency", "interactive
          // endophoric markers") read better stacked on two lines than
          // truncated mid-word ("commitment cons…"); single long words
          // fall back to character truncation, same convention as the PI
          // radar. Line 1 keeps the namespace word, line 2 the rest.
          const words = a.label.split(" ");
          let lines: string[] | null = null;
          if (a.label.length > 16 && words.length >= 2) {
            const l1 = words[0];
            const l2 = words.slice(1).join(" ");
            if (l1.length <= 14 && l2.length <= 18) lines = [l1, l2];
          }
          return (
            <g key={`axis-${i}`}>
              <line x1={C} y1={C} x2={outer.x} y2={outer.y} stroke="var(--border)" strokeWidth="0.7" />
              {lines ? (
                <text x={labelPos.x} y={labelPos.y} textAnchor="middle" className="pi-axis-label">
                  <tspan x={labelPos.x} dy="-4">{lines[0]}</tspan>
                  <tspan x={labelPos.x} dy="12">{lines[1]}</tspan>
                </text>
              ) : (
                <text x={labelPos.x} y={labelPos.y} textAnchor="middle" dominantBaseline="middle" className="pi-axis-label">
                  {a.label.length > 16 ? `${a.label.slice(0, 15)}…` : a.label}
                </text>
              )}
              <title>{title}</title>
            </g>
          );
        })}
        {empty ? (
          <text
            x={C}
            y={C}
            textAnchor="middle"
            dominantBaseline="middle"
            className="pi-axis-label"
          >
            {noHitsLabel ?? " "}
          </text>
        ) : (
          <>
            <polygon points={polygon} fill={ACCENT} fillOpacity="0.16" stroke={ACCENT} strokeWidth="1.6" />
            {/* Vertex dots: the profile shape stays legible even when one
                category dominates and the remaining axes hug the center. */}
            {vertices.map((v) => (
              <circle key={v.key} cx={v.x} cy={v.y} r="2.4" fill={ACCENT} stroke="none" />
            ))}
          </>
        )}
      </svg>
    </div>
  );
}
