/**
 * ChartExportButtons — v1.2.10 field fixes: one-click "Export PNG" /
 * "Export CSV" affordances for the analysis charts (Discourse bar charts,
 * both radars, the cue co-occurrence table). Deliberately separate from
 * the existing ExportButton (the multi-format data dropdown): these are
 * single-purpose graph buttons per the field request — visible, labeled,
 * no menu. Built as shared components so other analysis tabs can adopt
 * them without new plumbing:
 *
 * - ChartExportButton finds the inline SVG inside `targetRef` and
 *   rasterizes it with the chart's computed theme colors (see
 *   lib/chartExport.ts) — the PNG matches the on-screen chart and is
 *   saved through the app-wide download (native dialog under Tauri).
 * - ChartCsvExportButton emits an RFC-4180 file with a UTF-8 BOM, so
 *   Arabic text opens cleanly in Excel/Sheets.
 *
 * Both degrade quietly: export is a client-side blob download, no engine
 * round-trip, and failures are console warnings (never app-breaking).
 */
import { useState } from "react";

import { exportRowsAsCsv, exportSvgAsPng } from "@/lib/chartExport";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

export function ChartExportButton({
  targetRef,
  filename,
}: {
  targetRef: React.RefObject<HTMLElement | null> | React.RefObject<SVGSVGElement | null>;
  filename: string;
}) {
  const lang = useUI((s) => s.lang);
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      className="chart-export-btn"
      disabled={busy}
      onClick={() => {
        const svg = targetRef.current?.querySelector("svg");
        if (!svg) return;
        setBusy(true);
        exportSvgAsPng(svg as SVGSVGElement, filename)
          .catch((err: unknown) => console.warn("chart export failed", err))
          .finally(() => setBusy(false));
      }}
    >
      {t(lang, "chart_export_png")}
    </button>
  );
}

export function ChartCsvExportButton({
  headers,
  rows,
  filename,
}: {
  headers: string[];
  rows: Array<Array<string | number>>;
  filename: string;
}) {
  const lang = useUI((s) => s.lang);
  return (
    <button
      type="button"
      className="chart-export-btn"
      onClick={() => {
        try {
          exportRowsAsCsv(headers, rows, filename);
        } catch (err) {
          console.warn("csv export failed", err);
        }
      }}
    >
      {t(lang, "chart_export_csv")}
    </button>
  );
}
