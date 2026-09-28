/**
 * PersuasionRadar — v1.2.7 (§4) radar over the 15 persuasion-index
 * dimensions, grouped into the classical rhetorical triad
 * (logos / ethos / pathos). v1.2.8 (review #1): the grouping now mirrors
 * the package's own dimension inventory exactly (grounded against
 * persuasion-index 0.3.0): Logos 5, Ethos 4, Pathos 6 — so the UI can
 * never silently drop or misfile a dimension. The grouping itself is our
 * analysis-facing interpretation, stated in the UI citation.
 *
 * Pure inline SVG, no chart dependency — consistent with the repo's
 * offline-first PWA stance. Axis order is fixed (logos → ethos → pathos,
 * alphabetical within family) so the polygon shape is deterministic.
 */
import { useRef } from "react";

import { ChartExportButton } from "@/components/ChartExportButtons";
import type { DiscourseCategory } from "@/lib/api";

export const PI_FAMILY_AXES: Record<string, string[]> = {
  logos: ["Evidence", "Logic/Cohesion", "Specificity", "Argumentation", "Opponent’s View"],
  ethos: ["Authority/Credibility", "Commitment", "Politeness", "Style"],
  pathos: [
    "Engagement",
    "Impact",
    "Propaganda",
    "Reciprocity",
    "Scarcity/Urgency",
    "Sentiment",
  ],
};

const FAMILY_COLOR: Record<string, string> = {
  logos: "var(--tool3-accent)",
  ethos: "var(--tool1-accent)",
  pathos: "var(--tool4-accent)",
};

export function PersuasionRadar({
  categories,
  exportName = "corpusmind-pi-radar",
}: {
  categories: Record<string, DiscourseCategory>;
  /** Download name for the Export PNG button (no extension). */
  exportName?: string;
}) {
  // v1.2.10 field fixes: enlarged to match the TaxonomyRadar (420 units,
  // 520px cap) and the family legend moves BELOW the chart (centered row)
  // — it used to sit to the right, reading as captions of a small chart.
  const SIZE = 420;
  const C = SIZE / 2;
  const R = 150;
  const svgRef = useRef<SVGSVGElement | null>(null);
  const RINGS = [25, 50, 75, 100];

  const axes: Array<{ family: string; dim: string; value: number; angle: number }> = [];
  for (const family of Object.keys(PI_FAMILY_AXES)) {
    for (const dim of PI_FAMILY_AXES[family]) {
      const key = `pi.${family}.${dim}`;
      const info = categories[key];
      const value = info ? Math.max(0, Math.min(100, Number(info.freq) || 0)) : 0;
      // angle set below after we know the total count
      axes.push({ family, dim, value, angle: 0 });
    }
  }
  const n = axes.length || 1;
  axes.forEach((a, i) => {
    a.angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
  });

  const pt = (angle: number, radius: number) => ({
    x: C + radius * Math.cos(angle),
    y: C + radius * Math.sin(angle),
  });

  const familyMeans: Record<string, number> = {};
  for (const family of Object.keys(PI_FAMILY_AXES)) {
    const vals = axes.filter((a) => a.family === family).map((a) => a.value);
    familyMeans[family] = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : 0;
  }

  return (
    <div className="pi-radar-wrap">
      <div className="radar-toolbar">
        <ChartExportButton targetRef={svgRef} filename={exportName} />
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${SIZE} ${SIZE}`} width="100%" role="img" aria-label="Persuasion Index radar">
        {RINGS.map((r) => (
          <circle key={r} cx={C} cy={C} r={(R * r) / 100} fill="none" stroke="var(--border)" strokeWidth="0.7" />
        ))}
        {axes.map((a, i) => {
          const outer = pt(a.angle, R);
          const labelPos = pt(a.angle, R + 18);
          return (
            <g key={`axis-${i}`}>
              <line x1={C} y1={C} x2={outer.x} y2={outer.y} stroke="var(--border)" strokeWidth="0.7" />
              <text x={labelPos.x} y={labelPos.y} textAnchor="middle" dominantBaseline="middle" className="pi-axis-label">
                {a.dim.length > 16 ? `${a.dim.slice(0, 15)}…` : a.dim}
              </text>
            </g>
          );
        })}
        {Object.keys(PI_FAMILY_AXES).map((family) => {
          const pts = axes
            .filter((a) => a.family === family)
            .map((a) => pt(a.angle, (R * a.value) / 100))
            .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
            .join(" ");
          return <polygon key={family} points={pts} fill={FAMILY_COLOR[family]} fillOpacity="0.16" stroke={FAMILY_COLOR[family]} strokeWidth="1.6" />;
        })}
      </svg>
      <div className="pi-radar-legend">
        {Object.keys(PI_FAMILY_AXES).map((family) => (
          <span key={family} className="pi-legend-item">
            <span className="pi-legend-swatch" style={{ background: FAMILY_COLOR[family] }} />
            {family}: {familyMeans[family].toFixed(1)}
          </span>
        ))}
      </div>
    </div>
  );
}
