/**
 * ExportButton — a dropdown button for exporting analysis results in
 * multiple formats (xlsx, csv, tsv, txt, json) plus optional diagram
 * formats (svg, png) for collocation networks.
 *
 * Usage:
 *   <ExportButton
 *     label="Export"
 *     onExport={(fmt) => downloadBlob(blobFor(fmt), `results.${fmt}`)}
 *   />
 *   <ExportButton
 *     label="Export diagram"
 *     formats={["svg", "png"]}
 *     onExport={(fmt) => downloadBlob(blobFor(fmt), `network.${fmt}`)}
 *   />
 */
import { useState, useRef, useEffect } from "react";
import type { ExportFormat } from "@/lib/api";

interface ExportButtonProps {
  label?: string;
  onExport: (fmt: ExportFormat | "svg" | "png") => void;
  disabled?: boolean;
  formats?: Array<ExportFormat | "svg" | "png">;
}

const DEFAULT_FORMATS: Array<ExportFormat | "svg" | "png"> = ["xlsx", "csv", "tsv", "txt", "json"];

const FORMAT_LABELS: Record<string, string> = {
  xlsx: "Excel (.xlsx)",
  csv: "CSV (.csv)",
  tsv: "TSV (.tsv)",
  txt: "Plain text (.txt)",
  json: "JSON (.json)",
  svg: "SVG diagram (.svg)",
  png: "PNG image (.png)",
};

const FORMAT_HINTS: Record<string, string> = {
  xlsx: "Styled spreadsheet — opens in Excel/Sheets",
  csv: "Universal comma-separated — any tool",
  tsv: "Tab-separated — paste into Excel/Sheets",
  txt: "Plain text table — for emails / quick view",
  json: "Structured — for programmatic use / re-import",
  svg: "Vector diagram — scales to any size, for papers/slides",
  png: "Raster image 1600x1200 — for Word docs / social media",
};

export function ExportButton({
  label = "Export",
  onExport,
  disabled = false,
  formats = DEFAULT_FORMATS,
}: ExportButtonProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="export-dropdown" ref={ref}>
      <button
        className="btn-small export-trigger"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        title="Export results"
      >
        {label} {"\u25BE"}
      </button>
      {open && (
        <div className="export-menu" role="menu">
          {formats.map((fmt) => (
            <button
              key={fmt}
              className="export-menu-item"
              onClick={() => {
                onExport(fmt);
                setOpen(false);
              }}
              title={FORMAT_HINTS[fmt]}
            >
              <span className="export-menu-label">{FORMAT_LABELS[fmt] ?? fmt}</span>
              <span className="export-menu-hint">{FORMAT_HINTS[fmt]}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
