/**
 * resultExport — shared client-side export plumbing (v1.2.13-1).
 *
 * v1.0.1/Issue 5 put the "export the data already on screen" helpers inside
 * AnalysisView; v1.2.13-1 lifts them into a shared module so other views can
 * offer the same xlsx/csv/tsv/txt/json dropdown without duplicating (or
 * diverging from) the serialization rules:
 *
 *   - downloadJsonResult  — generic "flatten whatever object/array this is"
 *   - flattenDataToTable  — heuristic object/array → {headers, rows}
 *   - serializeTable      — table → bytes per format (BOM'd CSV/TSV so
 *                           Arabic opens cleanly in Excel; xlsx is the
 *                           HTML-table-with-.xlsx-extension fallback, as
 *                           documented in AnalysisView since Issue 5)
 *   - downloadTable       — curated {headers, rows} → file (used when the
 *                           caller knows the exact columns, e.g. the Arabic
 *                           Tools result tables)
 *   - useExportStatus     — the shared export-feedback hook (Issue 5)
 *
 * Domain-specific shapers:
 *   - arabicResultToTable    — one curated table per Arabic Tools tool, so
 *                              the exported file matches what the user sees
 *                              on screen (v1.2.13-1: Arabic Tools Export).
 *   - concordanceLinesToTable — KWIC lines in reading order for client-side
 *                              CQL concordance export (the engine's export
 *                              endpoint re-runs a *simple* query, which
 *                              cannot represent a CQL pattern, so CQL mode
 *                              exports the fetched lines client-side).
 */
import { useState } from "react";
import clsx from "clsx";

import { type ConcordanceLine } from "@/lib/api";

export type ExportStatus = (msg: string, kind: "success" | "error" | "info") => void;

// Issue 5: shared export-status hook so every panel gets the same
// user-visible success/error feedback without duplicating the boilerplate.
export function useExportStatus() {
  const [status, setStatus] = useState<{ kind: "success" | "error" | "info"; msg: string } | null>(null);
  const set = (msg: string, kind: "success" | "error" | "info" = "info") => {
    setStatus({ kind, msg });
    if (msg) setTimeout(() => setStatus(null), 8000);
  };
  const el = status && status.msg ? (
    <div className={clsx("uploader-status", status.kind)} style={{ marginTop: "var(--space-2)" }}>
      {status.msg}
    </div>
  ) : null;
  return { set, el };
}

/** Flatten an arbitrary result object into a table (headers + rows) for export. */
export function flattenDataToTable(data: unknown): { headers: string[]; rows: string[][] } {
  if (Array.isArray(data)) {
    // Array of objects — extract headers from first element
    if (data.length === 0) return { headers: [], rows: [] };
    const first = data[0];
    if (typeof first === "object" && first !== null) {
      const headers = Object.keys(first);
      const rows = data.map((item) => headers.map((h) => String((item as any)[h] ?? "")));
      return { headers, rows };
    }
    // Array of primitives
    return { headers: ["value"], rows: data.map((v) => [String(v)]) };
  }
  if (typeof data === "object" && data !== null) {
    // Single object — try to find array properties and export those
    const obj = data as Record<string, unknown>;
    for (const key of Object.keys(obj)) {
      if (Array.isArray(obj[key]) && obj[key].length > 0 && typeof obj[key][0] === "object") {
        const headers = Object.keys(obj[key][0] as object);
        const rows = (obj[key] as unknown[]).map((item) =>
          headers.map((h) => String((item as Record<string, unknown>)[h] ?? "")),
        );
        return { headers, rows };
      }
    }
    // No arrays found — export key/value pairs
    const headers = ["key", "value"];
    const rows = Object.entries(obj).map(([k, v]) => [k, String(v)]);
    return { headers, rows };
  }
  return { headers: ["value"], rows: [[String(data)]] };
}

/** Serialize a table to the requested format (client-side, no backend needed). */
export function serializeTable(headers: string[], rows: string[][], fmt: string): Uint8Array {
  if (fmt === "csv" || fmt === "tsv") {
    const delim = fmt === "csv" ? "," : "\t";
    const lines = [headers.join(delim)];
    for (const row of rows) {
      lines.push(row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(delim));
    }
    // Add UTF-8 BOM for Excel compatibility
    const text = "\uFEFF" + lines.join("\n");
    return new TextEncoder().encode(text);
  }
  if (fmt === "txt") {
    // Fixed-width text
    const widths = headers.map((h, i) =>
      Math.max(h.length, ...rows.map((r) => String(r[i] ?? "").length)),
    );
    const lines = [
      headers.map((h, i) => h.padEnd(widths[i])).join(""),
      "-".repeat(widths.reduce((a, b) => a + b, 0)),
      ...rows.map((r) => r.map((cell, i) => String(cell).padEnd(widths[i])).join("")),
    ];
    return new TextEncoder().encode(lines.join("\n"));
  }
  if (fmt === "xlsx") {
    // Use openpyxl-style XML (minimal XLSX) — or fall back to CSV with .xlsx extension
    // Since we can't generate real XLSX in the browser without a library,
    // generate an HTML table that Excel can open, with the .xlsx extension.
    // The user gets a file that opens in Excel. Not ideal, but better than JSON.
    const lines = [
      '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">',
      "<head><meta charset=\"utf-8\"></head><body><table border=\"1\">",
      "<tr>" + headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("") + "</tr>",
      ...rows.map((r) => "<tr>" + r.map((c) => `<td>${escapeHtml(c)}</td>`).join("") + "</tr>"),
      "</table></body></html>",
    ];
    return new TextEncoder().encode(lines.join(""));
  }
  // Default: JSON
  return new TextEncoder().encode(JSON.stringify({ headers, rows }, null, 2));
}

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const MIME_BY_EXT: Record<string, string> = {
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  csv: "text/csv; charset=utf-8",
  tsv: "text/tab-separated-values; charset=utf-8",
  txt: "text/plain; charset=utf-8",
  json: "application/json",
};

// v1.2.13-1: helper for callers that already know the exact table they want
// in the file (Arabic Tools result tables, CQL concordance lines) — same
// format/serialization path as downloadJsonResult, minus the flattening.
export async function downloadTable(
  headers: string[],
  rows: string[][],
  filename: string,
  setStatus: ExportStatus,
) {
  const { exportWithFeedback } = await import("@/lib/api");
  const ext = filename.split(".").pop()?.toLowerCase() || "json";
  let blob: Blob;
  if (ext === "json") {
    blob = new Blob([JSON.stringify({ headers, rows }, null, 2)], { type: "application/json" });
  } else {
    const serialized = serializeTable(headers, rows, ext);
    blob = new Blob([serialized as unknown as ArrayBuffer], {
      type: MIME_BY_EXT[ext] ?? "application/octet-stream",
    });
  }
  await exportWithFeedback(async () => blob, filename, setStatus);
}

// Issue 5: helper for panels that export client-side result data (no
// backend round-trip — the data is already in `result.data`). Now properly
// serializes to the chosen format (xlsx/csv/tsv/txt/json) instead of always
// dumping JSON regardless of format.
export async function downloadJsonResult(
  data: unknown,
  filename: string,
  setStatus: ExportStatus,
) {
  // Extract the extension from the filename to determine format
  const ext = filename.split(".").pop()?.toLowerCase() || "json";
  // Convert the data to the requested format
  if (ext === "json") {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const { exportWithFeedback } = await import("@/lib/api");
    await exportWithFeedback(async () => blob, filename, setStatus);
    return;
  }
  const { headers, rows } = flattenDataToTable(data);
  await downloadTable(headers, rows, filename, setStatus);
}

// --------------------------------------------------------------------- //
// Arabic Tools result → curated table (v1.2.13-1: Arabic Tools Export)
// --------------------------------------------------------------------- //

const MISS = "-";

/**
 * One curated table per Arabic Tools tool, matching the on-screen columns.
 * Falls back to the generic flattener for unknown payloads, so a new tool
 * added to the view still exports something sane rather than crashing.
 */
export function arabicResultToTable(result: { kind: string; data: any }): { headers: string[]; rows: string[][] } {
  const s = (v: unknown) => (v === null || v === undefined || v === "" ? MISS : String(v));
  switch (result?.kind) {
    case "morphology":
      return {
        headers: ["Token", "Root (الجذر)", "Pattern (الوزن)", "Lemma", "POS", "Stem", "Buckwalter"],
        rows: (result.data?.tokens ?? []).map((t: any) => [
          s(t?.text), s(t?.root), s(t?.pattern), s(t?.lemma), s(t?.pos), s(t?.stem), s(t?.buckwalter),
        ]),
      };
    case "roots":
      return {
        headers: ["Token", "Root (الجذر)", "Pattern (الوزن)", "Lemma", "POS"],
        rows: (result.data?.roots ?? []).map((r: any) => [
          s(r?.token), s(r?.root), s(r?.pattern), s(r?.lemma), s(r?.pos),
        ]),
      };
    case "clitics":
      return {
        headers: ["Surface", "Stem", "POS"],
        rows: (result.data?.segments ?? []).map((seg: any) => [
          s(seg?.surface), s(seg?.stem), s(seg?.pos),
        ]),
      };
    case "buckwalter":
      return {
        headers: ["Original", "Buckwalter"],
        rows: [[s(result.data?.original), s(result.data?.buckwalter)]],
      };
    case "dediac":
      return {
        headers: ["Original", "Dediacritized"],
        rows: [[s(result.data?.original), s(result.data?.dediacritized)]],
      };
    case "normalize":
      return {
        headers: ["Original", "Normalized"],
        rows: [[s(result.data?.original), s(result.data?.normalized)]],
      };
    case "dialect":
    case "register": {
      const dist = result.data?.dialect_distribution ?? result.data?.register_distribution ?? {};
      const header = result.kind === "dialect" ? "Dialect" : "Register";
      return {
        headers: [header, "Probability"],
        rows: Object.entries(dist)
          .sort(([, a]: any, [, b]: any) => Number(b) - Number(a))
          .map(([k, p]: any) => [String(k), (Number(p) * 100).toFixed(1) + "%"]),
      };
    }
    case "translate":
      return {
        headers: ["Word", "Direction", "Equivalent"],
        rows: (result.data?.equivalents?.length
          ? (result.data.equivalents as string[]).map((eq) => [s(result.data?.word), s(result.data?.direction), eq])
          : [[s(result.data?.word), s(result.data?.direction), MISS]]),
      };
    default:
      return flattenDataToTable(result?.data ?? result);
  }
}

// --------------------------------------------------------------------- //
// CQL concordance export (v1.2.13-1)
// --------------------------------------------------------------------- //

/**
 * KWIC lines in reading order. Used by CQL mode, where the engine's export
 * endpoint cannot be used (it re-runs the query as a *simple* concordance
 * and would silently return wrong rows for a CQL pattern).
 */
export function concordanceLinesToTable(lines: ConcordanceLine[]): { headers: string[]; rows: string[][] } {
  return {
    headers: ["Left context", "Node", "Right context", "POS", "Lemma", "Document", "Line ID"],
    rows: (lines ?? []).map((l) => [
      l.left ?? "", l.node ?? "", l.right ?? "", l.pos ?? "", l.lemma ?? "",
      l.document_filename ?? "", l.line_id ?? "",
    ]),
  };
}
