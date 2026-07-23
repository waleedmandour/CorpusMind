/**
 * Analysis -- frequency, collocation, keyness, dispersion, n-grams, POS,
 * grammar, dependency, discourse, vocabulary, sentiment, metaphor.
 *
 * The active sub-tab is driven by the sidebar navigation (activeNav in
 * the UI store). When the user clicks "Frequency" in the sidebar, this
 * view receives "frequency" as the active tab and renders that panel.
 * The internal tab bar also allows switching between analyses.
 */
import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api, exportWithFeedback, type ExportFormat, type ReferenceCorpusEntry } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { ExportButton } from "@/components/ExportButton";

// Issue 5: shared export-status hook so every analysis panel gets the same
// user-visible success/error feedback without duplicating the boilerplate.
function useExportStatus() {
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

// Issue 5: helper for panels that export client-side result data (no
// backend round-trip — the data is already in `result.data`). Now properly
// serializes to the chosen format (xlsx/csv/tsv/txt/json) instead of always
// dumping JSON regardless of format.
async function downloadJsonResult(
  data: unknown,
  filename: string,
  setStatus: (msg: string, kind: "success" | "error" | "info") => void,
) {
  const { exportWithFeedback } = await import("@/lib/api");
  // Extract the extension from the filename to determine format
  const ext = filename.split(".").pop()?.toLowerCase() || "json";
  // Convert the data to the requested format
  let blob: Blob;
  if (ext === "json") {
    blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  } else {
    // For xlsx/csv/tsv/txt, flatten the data to a table and serialize client-side
    const { rows, headers } = flattenDataToTable(data);
    const serialized = serializeTable(headers, rows, ext);
    const mimeType = ext === "xlsx"
      ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      : ext === "csv"
      ? "text/csv; charset=utf-8"
      : ext === "tsv"
      ? "text/tab-separated-values; charset=utf-8"
      : "text/plain; charset=utf-8";
    blob = new Blob([serialized as unknown as ArrayBuffer], { type: mimeType });
  }
  await exportWithFeedback(
    async () => blob,
    filename,
    setStatus,
  );
}

/** Flatten an arbitrary result object into a table (headers + rows) for export. */
function flattenDataToTable(data: unknown): { headers: string[]; rows: string[][] } {
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
function serializeTable(headers: string[], rows: string[][], fmt: string): Uint8Array {
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

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

type Tab =
  | "frequency" | "collocation" | "keyness" | "dispersion"
  | "ngrams" | "pos" | "grammar" | "dep" | "discourse" | "vocab" | "sentiment" | "metaphor";

const NAV_TO_TAB: Record<string, Tab> = {
  frequency: "frequency",
  collocation: "collocation",
  keyness: "keyness",
  dispersion: "dispersion",
  ngrams: "ngrams",
  pos: "pos",
  grammar: "grammar",
  dependency: "dep",
  discourse: "discourse",
  vocab: "vocab",
  sentiment: "sentiment",
  metaphor: "metaphor",
};

const TABS: { id: Tab; label: string; phase: 1 | 2 }[] = [
  { id: "frequency", label: "Frequency", phase: 1 },
  { id: "collocation", label: "Collocation", phase: 1 },
  { id: "keyness", label: "Keyness", phase: 1 },
  { id: "dispersion", label: "Dispersion", phase: 1 },
  { id: "ngrams", label: "N-grams", phase: 2 },
  { id: "pos", label: "POS", phase: 2 },
  { id: "grammar", label: "Grammar", phase: 2 },
  { id: "dep", label: "Dependency", phase: 2 },
  { id: "discourse", label: "Discourse", phase: 2 },
  { id: "vocab", label: "Vocabulary", phase: 2 },
  { id: "sentiment", label: "Sentiment", phase: 2 },
  { id: "metaphor", label: "Metaphor", phase: 2 },
];

export function AnalysisView() {
  const cid = useApp((s) => s.activeCorpusId);
  const activeNav = useUI((s) => s.activeNav);
  const [tab, setTab] = useState<Tab>("frequency");

  // Sync the internal tab with the sidebar navigation
  useEffect(() => {
    const mapped = NAV_TO_TAB[activeNav];
    if (mapped) setTab(mapped);
  }, [activeNav]);

  if (!cid) return <div className="empty-state">Select a corpus to analyze. Go to <strong>Corpora Selection → Your Corpus</strong> in the sidebar to create a corpus and upload texts.</div>;

  return (
    <div className="analysis">
      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={clsx("tab", { active: tab === t.id, "phase-2": t.phase === 2 })}
            onClick={() => setTab(t.id)}
            title={t.phase === 2 ? "Phase 2 feature" : undefined}
          >
            {t.label}{t.phase === 2 ? " 2" : ""}
          </button>
        ))}
      </div>

      {tab === "frequency" && <FrequencyPanel cid={cid} />}
      {tab === "collocation" && <CollocationPanel cid={cid} />}
      {tab === "keyness" && <KeynessPanel cid={cid} />}
      {tab === "dispersion" && <DispersionPanel cid={cid} />}
      {tab === "ngrams" && <NGramsPanel cid={cid} />}
      {tab === "pos" && <POSPanel cid={cid} />}
      {tab === "grammar" && <GrammarPanel cid={cid} />}
      {tab === "dep" && <DependencyPanel cid={cid} />}
      {tab === "discourse" && <DiscoursePanel cid={cid} />}
      {tab === "vocab" && <VocabPanel cid={cid} />}
      {tab === "sentiment" && <SentimentPanel cid={cid} />}
      {tab === "metaphor" && <MetaphorPanel cid={cid} />}
    </div>
  );
}


function FrequencyPanel({ cid }: { cid: string }) {
  const [unit, setUnit] = useState<"word" | "lemma" | "pos">("word");
  const [minFreq, setMinFreq] = useState(1);
  const result = useQuery({
    queryKey: ["frequency", cid, unit, minFreq],
    queryFn: () => api.frequency(cid, unit, minFreq, 200),
  });

  const exportStatus = useExportStatus();

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    await exportWithFeedback(
      () => api.exportFrequency(cid, unit, fmt as ExportFormat, 1000),
      `frequency_${unit}.${fmt}`,
      exportStatus.set,
    );
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Unit
          <select value={unit} onChange={(e) => setUnit(e.target.value as any)}>
            <option value="word">Word</option>
            <option value="lemma">Lemma</option>
            <option value="pos">POS tag</option>
          </select>
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <ExportButton onExport={onExport} disabled={!result.data} />
      </div>
      {exportStatus.el}

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens ·
            <strong> {result.data.total_types.toLocaleString()}</strong> types ·
            STTR (1000-token chunks) = <strong>{result.data.sttr.toFixed(4)}</strong>
          </div>
          <DataTable
            headers={[unit, "Frequency", "Per million", "%"]}
            rows={result.data.rows.map((r) => [r.item, r.freq, r.per_million, r.percent])}
          />
        </>
      )}
    </div>
  );
}


function CollocationPanel({ cid }: { cid: string }) {
  const [node, setNode] = useState("");
  const [level, setLevel] = useState<"word" | "lemma">("lemma");
  const [window, setWindow] = useState(5);
  const [minFreq, setMinFreq] = useState(3);
  const [submitted, setSubmitted] = useState<{ n: string; l: string; w: number; mf: number } | null>(null);

  const result = useQuery({
    queryKey: ["collocations", cid, submitted],
    queryFn: () => api.collocations(cid, submitted!.n, submitted!.l as any, submitted!.w, submitted!.mf),
    enabled: !!submitted,
  });

  const onSearch = () => {
    if (!node.trim()) return;
    setSubmitted({ n: node.trim(), l: level, w: window, mf: minFreq });
  };

  const exportStatus = useExportStatus();

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (!submitted) return;
    if (fmt === "svg") {
      await exportWithFeedback(
        () => api.exportCollocationNetworkSvg(cid, submitted.n, submitted.l as any, submitted.w, submitted.mf),
        `collocation_network_${submitted.n}.svg`,
        exportStatus.set,
      );
    } else if (fmt === "png") {
      await exportWithFeedback(
        () => api.exportCollocationNetworkPng(cid, submitted.n, submitted.l as any, submitted.w, submitted.mf),
        `collocation_network_${submitted.n}.png`,
        exportStatus.set,
      );
    } else {
      await exportWithFeedback(
        () => api.exportCollocations(cid, submitted.n, fmt, submitted.l as any, submitted.w, submitted.mf),
        `collocations_${submitted.n}.${fmt}`,
        exportStatus.set,
      );
    }
  };

  // Determine which measure columns to show
  const measureKeys = result.data?.rows[0]
    ? Object.keys(result.data.rows[0]).filter((k) =>
        !["collocate", "O", "fx", "fy", "N"].includes(k))
    : [];

  return (
    <div className="panel-content">
      <div className="toolbar">
        <input
          type="text"
          value={node}
          onChange={(e) => setNode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="Node word (e.g. 'fox')"
        />
        <label>Level
          <select value={level} onChange={(e) => setLevel(e.target.value as any)}>
            <option value="lemma">Lemma</option>
            <option value="word">Word</option>
          </select>
        </label>
        <label>Window
          <input type="number" min={1} max={20} value={window}
                 onChange={(e) => setWindow(Number(e.target.value))} />
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq}
                 onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <button onClick={onSearch} disabled={!node.trim()}>Compute</button>
        <ExportButton onExport={onExport} disabled={!result.data} />
        <ExportButton
          label="Export diagram"
          onExport={onExport}
          disabled={!result.data}
          formats={["svg", "png"]}
        />
      </div>

      <div className="grounding-notice">
        <strong>Reproducibility:</strong> every collocation result carries its window size
        and minimum frequency. A collocation measure without a stated window is not reproducible.
        All measures use the formulas in <code>docs/METHODOLOGY.md</code>.
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Node: <code>{result.data.node}</code> · Window ±{result.data.window} · Min freq {result.data.min_freq}
          </div>
          {result.data.rows.length === 0 ? (
            <div className="empty-state">No collocates met the min-frequency threshold.</div>
          ) : (
            <>
              <DataTable
                headers={["Collocate", "O", "f(node)", "f(y)", "N", ...measureKeys]}
                rows={result.data.rows.map((r) => [
                  r.collocate, r.O, r.fx, r.fy, r.N,
                  ...measureKeys.map((k) => (r as any)[k] ?? "—"),
                ])}
              />
              <Collocation3DNetwork
                node={result.data.node}
                rows={result.data.rows}
                measureKeys={measureKeys}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}


// ─── 3D Collocation Network Visualization ─────────────────────────
// An animated canvas-based 3D network graph that rotates and pulses.
// The node word sits at the center; collocates orbit around it.
// Edge thickness = co-occurrence frequency; node size = MI score.
// Colors: warm (strong association) → cool (weak).

interface CollocRow {
  collocate: string;
  O: number;
  fx: number;
  fy: number;
  N: number;
  [key: string]: any;
}

function Collocation3DNetwork({
  node,
  rows,
  measureKeys,
}: {
  node: string;
  rows: CollocRow[];
  measureKeys: string[];
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rotationRef = useRef(0);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;

    // Find MI scores for sizing/coloring
    const miKey = measureKeys.find((k) => k.toLowerCase().includes("mi")) || measureKeys[0];
    const maxMI = Math.max(...rows.map((r) => Math.abs(Number(r[miKey]) || 0)), 1);

    // Assign positions on a sphere for each collocate
    const nodes = rows.slice(0, 30).map((r, i) => {
      const phi = Math.acos(1 - (2 * (i + 1)) / (rows.length + 1));
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const radius = 120 + (1 - Math.abs(Number(r[miKey]) || 0) / maxMI) * 60;
      return {
        label: r.collocate,
        x: radius * Math.cos(theta) * Math.sin(phi),
        y: radius * Math.sin(theta) * Math.sin(phi),
        z: radius * Math.cos(phi),
        freq: r.O,
        mi: Math.abs(Number(r[miKey]) || 0),
      };
    });

    let animId = 0;

    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      const rot = rotationRef.current;

      // Sort nodes by z for proper depth ordering
      const projected = nodes.map((n) => {
        const cosR = Math.cos(rot);
        const sinR = Math.sin(rot);
        const x2 = n.x * cosR - n.z * sinR;
        const z2 = n.x * sinR + n.z * cosR;
        const scale = (z2 + 300) / 600; // depth scale (0=near, 1=far)
        return {
          ...n,
          px: cx + x2 * (1 + scale * 0.3),
          py: cy + n.y * (1 + scale * 0.3),
          pz: scale,
          x2,
          z2,
        };
      });
      projected.sort((a, b) => a.pz - b.pz);

      // Draw edges (center → each node)
      projected.forEach((n) => {
        const alpha = 0.15 + (1 - n.pz) * 0.5;
        const thickness = Math.max(0.5, n.freq / Math.max(...nodes.map((x) => x.freq)) * 4);
        ctx.strokeStyle = `rgba(11, 110, 79, ${alpha})`;
        ctx.lineWidth = thickness;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(n.px, n.py);
        ctx.stroke();
      });

      // Draw center node
      const centerGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, 40);
      centerGlow.addColorStop(0, "rgba(11, 110, 79, 0.4)");
      centerGlow.addColorStop(1, "rgba(11, 110, 79, 0)");
      ctx.fillStyle = centerGlow;
      ctx.fillRect(cx - 40, cy - 40, 80, 80);
      ctx.fillStyle = "#0b6e4f";
      ctx.beginPath();
      ctx.arc(cx, cy, 18, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.font = "bold 12px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(node, cx, cy);

      // Draw collocate nodes
      projected.forEach((n) => {
        const size = 6 + (n.mi / maxMI) * 12;
        const alpha = 0.4 + (1 - n.pz) * 0.6;
        // Color: warm for strong MI, cool for weak
        const heat = n.mi / maxMI;
        const r = Math.round(11 + heat * 200);
        const g = Math.round(110 - heat * 50);
        const b = Math.round(79 - heat * 60);
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx.beginPath();
        ctx.arc(n.px, n.py, size * (1 + n.pz * 0.3), 0, Math.PI * 2);
        ctx.fill();
        // Label
        if (size > 8) {
          ctx.fillStyle = `rgba(0, 0, 0, ${alpha})`;
          ctx.font = `${10 + size * 0.3}px Inter, sans-serif`;
          ctx.fillText(n.label, n.px, n.py);
        }
      });

      if (!pausedRef.current) {
        rotationRef.current += 0.005;
      }
      animId = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animId);
  }, [node, rows, measureKeys]);

  return (
    <div className="collocation-3d-network">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", maxWidth: "600px" }}>
        <h4 className="network-title">Collocation Network (3D Animated)</h4>
        <button
          className="btn-small"
          onClick={() => setPaused(!paused)}
          title={paused ? "Resume rotation" : "Pause rotation"}
          aria-label={paused ? "Resume rotation" : "Pause rotation"}
        >
          {paused ? "\u25B6" : "\u23F8"}
        </button>
      </div>
      <canvas
        ref={canvasRef}
        width={600}
        height={400}
        role="img"
        aria-label={`3D collocation network for '${node}' - see the table above for the same data in text form`}
        style={{
          width: "100%",
          maxWidth: "600px",
          height: "auto",
          background: "var(--bg-subtle, #f5f5f5)",
          borderRadius: "var(--radius-md, 8px)",
          border: "1px solid var(--border, #ddd)",
        }}
      />
      <p className="network-hint">
        Node size = association strength (MI). Edge thickness = co-occurrence frequency.
        Warm colors = stronger association. The network rotates automatically.
      </p>
    </div>
  );
}


function KeynessPanel({ cid }: { cid: string }) {
  const referenceCorpusId = useApp((s) => s.referenceCorpusId);
  const setReferenceCorpus = useApp((s) => s.setReferenceCorpus);
  const selectedReferenceName = useApp((s) => s.selectedReferenceName);
  const [minFreq, setMinFreq] = useState(5);

  // Need to list corpora in the active project to populate the reference picker
  const activeProjectId = useApp((s) => s.activeProjectId);
  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => api.listCorpora(activeProjectId!),
    enabled: !!activeProjectId,
  });

  // v0.1.17: also fetch the list of installed bundled references
  const refCorpora = useQuery({
    queryKey: ["reference-corpora"],
    queryFn: () => api.listReferenceCorpora(),
  });

  // Use the uploaded reference corpus if set, otherwise the selected bundled reference
  const result = useQuery({
    queryKey: ["keyness", cid, referenceCorpusId, selectedReferenceName, minFreq],
    queryFn: () => {
      if (referenceCorpusId) {
        return api.keyness(cid, referenceCorpusId, minFreq, 200);
      } else if (selectedReferenceName) {
        return api.keynessWithReference(cid, selectedReferenceName, minFreq, 200) as any;
      }
      throw new Error("No reference selected");
    },
    enabled: !!referenceCorpusId || !!selectedReferenceName,
  });

  const exportStatus = useExportStatus();

  const onExport = async (fmt: ExportFormat | "svg" | "png") => {
    if (referenceCorpusId) {
      await exportWithFeedback(
        () => api.exportKeyness(cid, referenceCorpusId, fmt as ExportFormat),
        `keyness.${fmt}`,
        exportStatus.set,
      );
    } else if (selectedReferenceName) {
      // For bundled references, export the keyness result as JSON
      const data = result.data;
      if (data) {
        await downloadJsonResult(data, `keyness_vs_${selectedReferenceName}.${fmt}`, exportStatus.set);
      }
    }
  };

  const onMethodsPdf = async () => {
    await exportWithFeedback(
      () => api.exportMethodsPdf(cid),
      `methods_section.pdf`,
      exportStatus.set,
    );
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Reference corpus
          <select value={referenceCorpusId ?? ""} onChange={(e) => setReferenceCorpus(e.target.value || null)}>
            <option value="">- Select uploaded corpus -</option>
            {corpora.data?.filter((c) => c.id !== cid).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        {/* v0.1.17: also show installed bundled reference frequency lists */}
        {refCorpora.data?.references.filter((r: ReferenceCorpusEntry) => r.installed).length ?? 0 > 0 ? (
          <label>or bundled reference
            <select
              value={selectedReferenceName ?? ""}
              onChange={(e) => useApp.getState().setSelectedReferenceName(e.target.value || null)}
              disabled={!!referenceCorpusId}
            >
              <option value="">- None -</option>
              {refCorpora.data?.references.filter((r: ReferenceCorpusEntry) => r.installed).map((r: ReferenceCorpusEntry) => (
                <option key={r.name} value={r.name}>{r.display_name}</option>
              ))}
            </select>
          </label>
        ) : null}
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <ExportButton onExport={onExport} disabled={!result.data} />
        <button onClick={onMethodsPdf}>Methods PDF</button>
      </div>
      {exportStatus.el}

      <div className="grounding-notice">
        <strong>4 Principle 3:</strong> a "key" word is never reported as important on
        frequency-of-occurrence-in-a-huge-corpus grounds alone. Log Ratio, %DIFF,
        Simple Maths, and Odds Ratio ride alongside log-likelihood - never report
        one without the other.
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Target N₁ = <strong>{result.data.N1.toLocaleString()}</strong> ·
            Reference N₂ = <strong>{result.data.N2.toLocaleString()}</strong>
          </div>
          <h3>Positive keywords (over-represented in target)</h3>
          <DataTable
            headers={["Term", "f1", "f2", "LL", "χ²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio"]}
            rows={(result.data as any).positive_keywords.map((r: any) => [
              r.term, r.f1, r.f2, fmt(r.log_likelihood), fmt(r.chi_square),
              fmt(r.log_ratio), fmt(r.pct_diff), fmt(r.simple_maths), fmt(r.odds_ratio),
            ])}
          />
          <h3>Negative keywords (under-represented in target)</h3>
          <DataTable
            headers={["Term", "f1", "f2", "LL", "χ²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio"]}
            rows={(result.data as any).negative_keywords.map((r: any) => [
              r.term, r.f1, r.f2, fmt(r.log_likelihood), fmt(r.chi_square),
              fmt(r.log_ratio), fmt(r.pct_diff), fmt(r.simple_maths), fmt(r.odds_ratio),
            ])}
          />
        </>
      )}
    </div>
  );
}


function DispersionPanel({ cid }: { cid: string }) {
  const [term, setTerm] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const result = useQuery({
    queryKey: ["dispersion", cid, submitted],
    queryFn: () => api.dispersion(cid, submitted!, "word"),
    enabled: !!submitted,
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      <div className="toolbar">
        <input
          type="text"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setSubmitted(term.trim())}
          placeholder="Term (e.g. 'the')"
        />
        <button onClick={() => setSubmitted(term.trim())} disabled={!term.trim()}>Compute</button>
        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `dispersion.${fmt}`, exportStatus.set); } } } disabled={!result.data} />
      </div>
      {exportStatus.el}

      {result.data && (
        <>
          <div className="result-meta">
            Juilland's D = <strong>{result.data.juillands_d}</strong> · Gries' DP = <strong>{result.data.gries_dp}</strong>
            <div className="hint">
              Juilland's D: 1 = perfectly even, 0 = maximally concentrated.
              Gries' DP: 0 = perfectly even, (n−1)/n = maximally concentrated.
            </div>
          </div>
          <h3>Frequency per document</h3>
          <div className="bar-chart">
            {result.data.per_part_freqs.map((f, i) => (
              <div key={i} className="bar-row">
                <span className="bar-label">Doc {i + 1}</span>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${(f / Math.max(...result.data.per_part_freqs, 1)) * 100}%` }} />
                </div>
                <span className="bar-value">{f}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}


function DataTable({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filter, setFilter] = useState("");

  // Detect if a column is numeric (all non-empty values are numbers)
  const isNumeric = (col: number) => rows.length > 0 && rows.every((r) => r[col] === "" || r[col] === null || typeof r[col] === "number");

  const sorted = [...rows];
  if (sortCol !== null) {
    const numeric = isNumeric(sortCol);
    sorted.sort((a, b) => {
      const av = a[sortCol];
      const bv = b[sortCol];
      if (av === "" || av === null) return 1;
      if (bv === "" || bv === null) return -1;
      let cmp: number;
      if (numeric) {
        cmp = Number(av) - Number(bv);
      } else {
        cmp = String(av).localeCompare(String(bv));
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }

  const filtered = filter.trim()
    ? sorted.filter((r) => r.some((c) => String(c).toLowerCase().includes(filter.toLowerCase())))
    : sorted;

  const cycleSort = (col: number) => {
    if (sortCol === col && sortDir === "asc") {
      setSortDir("desc");
    } else if (sortCol === col && sortDir === "desc") {
      setSortCol(null);
      setSortDir("asc");
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  };

  return (
    <div>
      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter results..."
        style={{ marginBottom: "var(--space-2)", padding: "4px 8px", fontSize: "12px", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", inlineSize: "100%", maxWidth: "300px" }}
      />
      <table className="data-table">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={h} onClick={() => cycleSort(i)} style={{ cursor: "pointer", userSelect: "none" }}>
                {h} {sortCol === i ? (sortDir === "asc" ? "\u25B2" : "\u25BC") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {filter.trim() && <p style={{ fontSize: "11px", color: "var(--text-subtle)", marginTop: "var(--space-1)" }}>Showing {filtered.length} of {rows.length} rows</p>}
    </div>
  );
}


function fmt(v: number | null): string {
  if (v === null || v === undefined) return "—";
  if (!isFinite(v)) return v > 0 ? "∞" : "-∞";
  return v.toFixed(4);
}


// =========================================================================
// Phase 2 panels
// =========================================================================


function NGramsPanel({ cid }: { cid: string }) {
  const [n, setN] = useState(2);
  const [minFreq, setMinFreq] = useState(2);
  const [minRange, setMinRange] = useState(1);
  const result = useQuery({
    queryKey: ["ngrams", cid, n, minFreq, minRange],
    queryFn: () => api.ngrams(cid, n, minFreq, minRange, 200),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>N
          <select value={n} onChange={(e) => setN(Number(e.target.value))}>
            {[2, 3, 4, 5, 6].map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <label>Min freq
          <input type="number" min={1} value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value))} />
        </label>
        <label>Min range (distinct docs)
          <input type="number" min={1} value={minRange} onChange={(e) => setMinRange(Number(e.target.value))} />
        </label>
      </div>
      {exportStatus.el}

      <div className="grounding-notice">
        <strong>Note:</strong> Lexical bundles require BOTH a minimum frequency per million words
        AND a minimum number of distinct texts - raw frequency alone is not enough to
        distinguish genuine bundles from single-text artifacts (Biber et al.).

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `ngrams.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens ·
            N = {result.data.n} · min_freq={result.data.min_freq} · min_range={result.data.min_range}
          </div>
          <DataTable
            headers={["N-gram", "Frequency", "Per million", "Range (docs)", "Range %"]}
            rows={result.data.rows.map((r) => [r.ngram, r.freq, r.per_million, r.range, r.range_percent])}
          />
        </>
      )}
    </div>
  );
}


function POSPanel({ cid }: { cid: string }) {
  const [n, setN] = useState(1);
  const result = useQuery({
    queryKey: ["pos", cid, n],
    queryFn: () => api.posAnalysis(cid, n, 2, 100),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>N
          <select value={n} onChange={(e) => setN(Number(e.target.value))}>
            <option value={1}>1 (distribution)</option>
            <option value={2}>2 (bigrams)</option>
            <option value={3}>3 (trigrams)</option>
            <option value={4}>4</option>
            <option value={5}>5</option>
          </select>
        </label>

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `pos.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>
      {exportStatus.el}

      {result.data && n === 1 && (
        <>
          <div className="result-meta"><strong>{result.data.total_tokens.toLocaleString()}</strong> tokens</div>
          <h3>POS distribution</h3>
          <DataTable
            headers={["POS", "Frequency", "%"]}
            rows={result.data.distribution.map((r) => [r.pos, r.freq, r.percent])}
          />
        </>
      )}
      {result.data && n >= 2 && (
        <>
          <div className="result-meta"><strong>{result.data.total_tokens.toLocaleString()}</strong> tokens</div>
          <h3>Top POS {n}-grams</h3>
          <DataTable
            headers={["Pattern", "Frequency"]}
            rows={result.data.pos_ngrams.map((r) => [r.pattern, r.freq])}
          />
        </>
      )}
    </div>
  );
}


const GRAMMAR_PATTERNS = ["passive_voice", "modal", "negation", "relative_clause", "complex_np", "tense"] as const;


function GrammarPanel({ cid }: { cid: string }) {
  const [selected, setSelected] = useState<string[]>(GRAMMAR_PATTERNS as unknown as string[]);
  const result = useQuery({
    queryKey: ["grammar", cid, selected],
    queryFn: () => api.grammar(cid, selected, 20),
  });
  const exportStatus = useExportStatus();

  const toggle = (p: string) => {
    setSelected((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]);
  };

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Patterns</label>
        {GRAMMAR_PATTERNS.map((p) => (
          <label key={p} className="checkbox">
            <input type="checkbox" checked={selected.includes(p)} onChange={() => toggle(p)} />
            {p}
          </label>
        ))}
      </div>
      {exportStatus.el}

      <div className="grounding-notice">
        <strong>Note:</strong> Grammar pattern detectors are <em>dependency-parse-driven</em>,
        not regex over surface text - so they generalize across genres.

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `grammar.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>

      {result.data && (
        <>
          <h3>Counts</h3>
          <DataTable
            headers={["Pattern", "Count"]}
            rows={Object.entries(result.data.counts).map(([p, c]) => [p, c])}
          />
          {Object.entries(result.data.patterns).map(([pat, examples]) => (
            examples.length > 0 && (
              <div key={pat}>
                <h3>{pat} - examples</h3>
                <ul className="grammar-examples">
                  {examples.map((ex, i) => {
                    const verb = String(ex.verb ?? "");
                    const modal = String(ex.modal ?? "");
                    const negator = String(ex.negator ?? "");
                    const head = String(ex.head ?? "");
                    const modifiers = Array.isArray(ex.modifiers) ? ex.modifiers.map(String) : [];
                    return (
                      <li key={i}>
                        <code className="evidence-ref">{ex.evidence_id}</code>
                        {verb && <span className="ex-verb">verb: <strong>{verb}</strong></span>}
                        {modal && <span className="ex-modal">modal: <strong>{modal}</strong></span>}
                        {negator && <span>negator: <strong>{negator}</strong></span>}
                        {head && modifiers.length > 0 && <span><strong>{head}</strong> ← {modifiers.join(", ")}</span>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )
          ))}
        </>
      )}
    </div>
  );
}


function DependencyPanel({ cid }: { cid: string }) {
  const [relation, setRelation] = useState("nsubj");
  const result = useQuery({
    queryKey: ["dep", cid, relation],
    queryFn: () => api.dependencies(cid, relation, 100),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      <div className="toolbar">
        <label>Relation
          <select value={relation} onChange={(e) => setRelation(e.target.value)}>
            <option value="nsubj">nsubj (subject)</option>
            <option value="obj">obj (object)</option>
            <option value="iobj">iobj (indirect object)</option>
            <option value="obl">obl (oblique)</option>
            <option value="amod">amod (adjectival modifier)</option>
            <option value="compound">compound</option>
          </select>
        </label>
      </div>
      {exportStatus.el}

      <div className="grounding-notice">
        <strong>Note:</strong> Built as thin queries over the same dependency parses already
        produced in 8.1 - not a separate pipeline.

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `dependency.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>

      {result.data && (
        <>
          <div className="result-meta">Relation: <code>{result.data.relation}</code></div>
          <DataTable
            headers={["Governor", "Dependent", "Frequency", "Example evidence IDs"]}
            rows={result.data.rows.map((r) => [r.governor, r.dependent, r.freq, r.examples.join(" · ")])}
          />
        </>
      )}
    </div>
  );
}


function DiscoursePanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["discourse", cid],
    queryFn: () => api.discourse(cid),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="grounding-notice">
        <strong>Note:</strong> Metadiscourse categories follow Hyland's interactive/interactional
        taxonomy (Hyland 2005) - this makes results citable and comparable across studies.

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `discourse.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>

      {result.data && (
        <>
          <div className="result-meta">
            Taxonomy: <strong>{result.data.taxonomy}</strong> ·
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens
          </div>
          {Object.entries(result.data.categories).map(([cat, info]) => (
            <div key={cat} className="discourse-cat">
              <h3>{cat} <span className="cat-meta">freq={info.freq} · {info.per_million}/M</span></h3>
              <ul className="discourse-examples">
                {info.examples.map((ex, i) => (
                  <li key={i}>
                    <code className="evidence-ref">{ex.evidence_id}</code>
                    <strong>{ex.cue}</strong>
                    <em>"{ex.sentence_preview}…"</em>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
    </div>
  );
}


function VocabPanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["vocab", cid],
    queryFn: () => api.vocabProfile(cid, 1, 100),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="grounding-notice">
        <strong>Note:</strong> Vocabulary profiling uses an open frequency-band approximation
        (CC-0 wordlist). EVP-style CEFR wordlists carry redistribution restrictions and are
        not bundled without confirmed rights.

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `vocab.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_tokens.toLocaleString()}</strong> tokens ·
            <strong>{result.data.total_types.toLocaleString()}</strong> types
          </div>
          <h3>Frequency bands</h3>
          <DataTable
            headers={["Band", "Frequency", "%"]}
            rows={result.data.bands.map((b) => [b.band, b.freq, b.percent])}
          />
          {result.data.academic_words.length > 0 && (
            <>
              <h3>Academic words (AWL)</h3>
              <DataTable
                headers={["Word", "Frequency"]}
                rows={result.data.academic_words.map((w) => [w.word, w.freq])}
              />
            </>
          )}
          {result.data.rare_words.length > 0 && (
            <>
              <h3>Rare words (frequency {"\u2264"} 1) {result.data.rare_words.length > 50 && <span style={{ fontSize: "11px", fontWeight: "normal", color: "var(--text-subtle)" }}>(showing top 50 of {result.data.rare_words.length})</span>}</h3>
              <DataTable
                headers={["Word", "Frequency"]}
                rows={result.data.rare_words.slice(0, 50).map((w) => [w.word, w.freq])}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}


function SentimentPanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["sentiment", cid],
    queryFn: () => api.sentiment(cid),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="grounding-notice">
        <strong>Note:</strong> Phase 2 uses a lexicon-based sentiment scorer. Phase 3 will swap
        in VADER or a transformers-based model behind the same interface - results stay comparable
        because the model + version is pinned per project (4 Principle 8).

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `sentiment.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>

      {result.data && (
        <>
          <div className="result-meta">
            <strong>{result.data.total_sentences}</strong> sentences ·
            avg score = <strong>{result.data.avg_score}</strong> (-1 to +1)
          </div>
          <div className="sentiment-bars">
            <div className="bar-row">
              <span className="bar-label">Positive</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(result.data.positive / result.data.total_sentences) * 100}%`, background: "var(--bar-positive)" }} /></div>
              <span className="bar-value">{result.data.positive}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Neutral</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(result.data.neutral / result.data.total_sentences) * 100}%`, background: "var(--bar-neutral)" }} /></div>
              <span className="bar-value">{result.data.neutral}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Negative</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(result.data.negative / result.data.total_sentences) * 100}%`, background: "var(--bar-negative)" }} /></div>
              <span className="bar-value">{result.data.negative}</span>
            </div>
          </div>
          <h3>Sentiment timeline (per sentence) {result.data.timeline.length > 100 && <span style={{ fontSize: "11px", fontWeight: "normal", color: "var(--text-subtle)" }}>(showing first 100 of {result.data.timeline.length})</span>}</h3>
          <div className="sentiment-timeline">
            {result.data.timeline.slice(0, 100).map((t, i) => (
              <div key={i} className="timeline-bar"
                style={{ height: `${Math.abs(t.score) * 40 + 2}px`,
                         background: t.score > 0 ? "var(--bar-positive)" : t.score < 0 ? "var(--bar-negative)" : "var(--bar-neutral)" }}
                title={`Sent ${t.sent}: score=${t.score} (pos=${t.pos_hits}, neg=${t.neg_hits})`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}


function MetaphorPanel({ cid }: { cid: string }) {
  const result = useQuery({
    queryKey: ["metaphor", cid],
    queryFn: () => api.metaphorCandidates(cid, 50),
  });
  const exportStatus = useExportStatus();

  return (
    <div className="panel-content">
      {exportStatus.el}
      <div className="grounding-notice">
        <strong>Note:</strong> These are <em>candidates only</em>.
        The LLM triages them via MIPVU decision steps (contextual vs. basic meaning,
        contrast-but-comprehensible-via-comparison test), and a <strong>human must
        verify</strong> before any candidate counts as a confirmed metaphor in export
        or statistics. Current evidence shows LLMs alone under-perform supervised
        detectors and especially struggle to filter literal false positives - the
        verification gate is not optional UI polish, it is load-bearing for validity.

        <ExportButton onExport={(fmt) => { if (result.data) { downloadJsonResult(result.data, `metaphor.${fmt}`, exportStatus.set); } } } disabled={!result.data} /></div>

      {result.data && (
        <>
          <div className="result-meta">
            Pipeline: <strong>{result.data.pipeline}</strong> ·
            <strong>{result.data.candidates.length}</strong> candidates ·
            <strong>{result.data.verified_count}</strong> verified
          </div>
          <ul className="metaphor-candidates">
            {result.data.candidates.map((c, i) => (
              <li key={i} className="metaphor-candidate">
                <header>
                  <code className="evidence-ref">{c.evidence_id}</code>
                  <strong className="metaphor-word">{c.word}</strong>
                  <span className="metaphor-pos">({c.pos})</span>
                  <span className="metaphor-subject">subject: <em>{c.subject}</em></span>
                  <button className="verify-btn" title="Coming soon - manual verification flow (Phase 3)" disabled>Needs verification</button>
                </header>
                <p className="metaphor-sentence">"{c.sentence}"</p>
                <p className="metaphor-reason">{c.reason}</p>
              </li>
            ))}
          </ul>
          {result.data.candidates.length === 0 && (
            <div className="empty-state">No metaphor candidates found in this corpus.</div>
          )}
        </>
      )}
    </div>
  );
}
