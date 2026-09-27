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
import type { DiscourseCategory } from "@/lib/api";

export const RADAR_MIN_AXES = 3;
export const RADAR_MAX_AXES = 12;

export function TaxonomyRadar({ categories }: { categories: Record<string, DiscourseCategory> }) {
  const SIZE = 320;
  const C = SIZE / 2;
  const R = 108;
  const RINGS = [25, 50, 75, 100];
  const ACCENT = "var(--tool2-accent)";

  const axes = Object.keys(categories)
    .sort((a, b) => a.localeCompare(b))
    .map((cat) => ({
      cat,
      label: cat.replace(/_/g, " "),
      freq: Math.max(0, Number(categories[cat]?.freq) || 0),
      angle: 0,
    }));
  const max = Math.max(...axes.map((a) => a.freq), 1);
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

  return (
    <div className="taxonomy-radar-wrap">
      <svg
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
          const labelPos = pt(a.angle, R + 14);
          const title = `${a.label}: ${a.freq.toLocaleString()} (of max ${max.toLocaleString()})`;
          return (
            <g key={`axis-${i}`}>
              <line x1={C} y1={C} x2={outer.x} y2={outer.y} stroke="var(--border)" strokeWidth="0.7" />
              <text x={labelPos.x} y={labelPos.y} textAnchor="middle" dominantBaseline="middle" className="pi-axis-label">
                {a.label.length > 16 ? `${a.label.slice(0, 15)}…` : a.label}
              </text>
              <title>{title}</title>
            </g>
          );
        })}
        <polygon points={polygon} fill={ACCENT} fillOpacity="0.16" stroke={ACCENT} strokeWidth="1.6" />
      </svg>
    </div>
  );
}
