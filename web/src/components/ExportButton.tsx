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
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

interface ExportButtonProps {
  label?: string;
  onExport: (fmt: ExportFormat | "svg" | "png") => void;
  disabled?: boolean;
  formats?: Array<ExportFormat | "svg" | "png">;
}

const DEFAULT_FORMATS: Array<ExportFormat | "svg" | "png"> = ["xlsx", "csv", "tsv", "txt", "json"];

// v1.2.14-7 (r7): format names stay as international format labels, but the
// descriptive hints and the txt/svg/png display names now follow the UI
// language. xlsx/csv/tsv/json keep their universal names in both languages.
const FORMAT_LABEL_KEYS: Partial<Record<string, Parameters<typeof t>[1]>> = {
  txt: "exp_fmt_txt",
  svg: "exp_fmt_svg",
  png: "exp_fmt_png",
};

const FORMAT_HINT_KEYS: Record<string, Parameters<typeof t>[1]> = {
  xlsx: "exp_hint_xlsx",
  csv: "exp_hint_csv",
  tsv: "exp_hint_tsv",
  txt: "exp_hint_txt",
  json: "exp_hint_json",
  svg: "exp_hint_svg",
  png: "exp_hint_png",
};

const STATIC_FORMAT_LABELS: Record<string, string> = {
  xlsx: "Excel (.xlsx)",
  csv: "CSV (.csv)",
  tsv: "TSV (.tsv)",
  json: "JSON (.json)",
};

export function ExportButton({
  label,
  onExport,
  disabled = false,
  formats = DEFAULT_FORMATS,
}: ExportButtonProps) {
  const lang = useUI((s) => s.lang);
  const effectiveLabel = label ?? t(lang, "exp_label");
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
        title={t(lang, "exp_menu_title")}
      >
        {effectiveLabel} {"\u25BE"}
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
              title={FORMAT_HINT_KEYS[fmt] ? t(lang, FORMAT_HINT_KEYS[fmt]) : undefined}
            >
              <span className="export-menu-label">
                {FORMAT_LABEL_KEYS[fmt]
                  ? t(lang, FORMAT_LABEL_KEYS[fmt])
                  : (STATIC_FORMAT_LABELS[fmt] ?? fmt)}
              </span>
              <span className="export-menu-hint">
                {FORMAT_HINT_KEYS[fmt] ? t(lang, FORMAT_HINT_KEYS[fmt]) : ""}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
