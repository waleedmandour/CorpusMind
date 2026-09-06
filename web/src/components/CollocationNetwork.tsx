/**
 * CollocationNetwork (v1.0.0) — interactive WebGL collocation network.
 *
 * Graphology + Sigma.js rewrite (user-reported: the previous canvas version
 * "appears small and not interactive"). Built on the NetworkX backend
 * (engine/api/network.py):
 *
 *   - Nodes = node word + its top collocates; size ∝ corpus frequency.
 *   - Edges = ±window co-occurrence; thickness ∝ the SELECTED association
 *     measure (all measures ship per edge, so switching measure never
 *     refetches — the reducer just re-reads precomputed normalized scores).
 *   - 7 measures: MI, T-score, log-likelihood, Dice, Log-Dice, χ², ΔP.
 *   - Click a collocate → its collocates are fetched server-side and merged
 *     in (progressive second-order expansion, no page refresh).
 *   - Click an expanded collocate again → collapse its branch.
 *   - Right-click a node → set as center (re-runs the query).
 *   - Hover → highlight ring + tooltip with the exact statistics.
 *   - Drag nodes to rearrange; wheel to zoom; drag the stage to pan.
 *   - ForceAtlas2 layout (graphology-layout-forceatlas2) re-run lazily
 *     after each expansion so clusters settle.
 *   - Export the network as PNG (composited WebGL layers) or JSON
 *     (full graph with positions + all statistics).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import Graph from "graphology";
import Sigma from "sigma";
import type { Attributes } from "graphology-types";
import forceAtlas2, { inferSettings } from "graphology-layout-forceatlas2";

import {
  api,
  downloadBlob,
  type CollocationMeasure,
  type CollocationNetworkEdge,
  type CollocationNetworkResult,
} from "@/lib/api";

// ─── Design tokens (match the CorpusMind dark-green system) ───────────────
const BRAND = "#1b4d3e";
const BRAND_NODE = "#2f7d5f";
const BRAND_EDGE = "rgba(27, 77, 62, 0.55)";
const HIGHLIGHT = "#e68c1e";

const MEASURES: Array<{ key: CollocationMeasure; label: string }> = [
  { key: "mi", label: "Mutual Information" },
  { key: "t_score", label: "T-score" },
  { key: "log_likelihood", label: "Log-likelihood" },
  { key: "dice", label: "Dice" },
  { key: "log_dice", label: "Log-Dice" },
  { key: "chi_square", label: "Chi-square" },
  { key: "delta_p", label: "ΔP (x→y)" },
];

const MAX_NODES = 120;
const INITIAL_TOP_N = 14;
const EXPAND_TOP_N = 8;

export interface CollocationNetworkProps {
  cid: string;
  centerNode: string;
  level: "word" | "lemma";
  window: number;
  minFreq: number;
  onSetCenter?: (word: string) => void;
}

/** Deterministic circle seed — FA2 refines from here. */
function seedPositions(graph: Graph) {
  const n = Math.max(graph.order, 1);
  let i = 0;
  graph.forEachNode((node) => {
    const angle = (2 * Math.PI * i) / n;
    graph.setNodeAttribute(node, "x", Math.cos(angle) * (1 + (i % 3) * 0.1));
    graph.setNodeAttribute(node, "y", Math.sin(angle) * (1 + (i % 3) * 0.1));
    i += 1;
  });
}

function runLayout(graph: Graph, iterations: number) {
  if (graph.order < 3) return;
  forceAtlas2.assign(graph, {
    iterations,
    settings: {
      ...inferSettings(graph),
      gravity: 1.2,
      scalingRatio: 8,
      barnesHutOptimize: false,
      adjustSizes: true,
    },
  });
}

export function CollocationNetwork({
  cid,
  centerNode,
  level,
  window: win,
  minFreq,
  onSetCenter,
}: CollocationNetworkProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const draggingRef = useRef<string | null>(null);
  const hoverRef = useRef<string | null>(null);
  const measureRef = useRef<CollocationMeasure>("mi");

  const [measure, setMeasure] = useState<CollocationMeasure>("mi");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [stats, setStats] = useState({ nodes: 0, edges: 0, density: 0 });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const [flash, setFlash] = useState("");
  const [empty, setEmpty] = useState(false);
  // v1.0.7: persistent load-error line (the 2.6s flash used to swallow real
  // failures — e.g. a reducer exception — leaving a silently blank canvas).
  const [loadError, setLoadError] = useState("");

  const qc = useQueryClient();

  const flashMsg = useCallback((msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(""), 2600);
  }, []);

  // ── Build the graphology graph from a network response ──────────────────
  const buildGraph = useCallback((res: CollocationNetworkResult): Graph => {
    const graph = new Graph();
    const maxFreq = Math.max(...res.nodes.map((n) => n.freq), 1);
    for (const node of res.nodes) {
      graph.addNode(node.id, {
        freq: node.freq,
        degree: node.degree,
        strength: node.strength,
        isCenter: node.is_center,
        size: node.is_center ? 16 : 5 + 9 * Math.sqrt(node.freq / maxFreq),
        label: node.id,
        x: 0,
        y: 0,
      });
    }
    for (const edge of res.edges) {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      if (graph.hasEdge(edge.source, edge.target)) continue;
      graph.addEdge(edge.source, edge.target, {
        ...edge,
        norms: normalizeEdge(edge, res.edges),
      });
    }
    seedPositions(graph);
    runLayout(graph, 140);
    return graph;
  }, []);

  // ── Initial load ────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setEmpty(false);
    setLoadError("");
    (async () => {
      try {
        const res = await api.collocationNetwork(cid, {
          node: centerNode,
          level,
          window: win,
          min_freq: minFreq,
          measure: "mi",
          top_n: INITIAL_TOP_N,
          depth: 2,
          max_nodes: MAX_NODES,
        });
        if (cancelled) return;
        if (res.nodes.length === 0) {
          flashMsg(`No collocates found for “${centerNode}” at ±${win} / min freq ${minFreq}.`);
          graphRef.current = null;
          sigmaRef.current?.setGraph(new Graph());
          sigmaRef.current?.refresh();
          setStats({ nodes: 0, edges: 0, density: 0 });
          setEmpty(true);
          return;
        }
        graphRef.current = buildGraph(res);
        setStats(res.stats);
        setExpanded(new Set());
        sigmaRef.current?.setGraph(graphRef.current);
        sigmaRef.current?.refresh();
      } catch (e) {
        if (!cancelled) {
          setLoadError(`Network failed: ${(e as Error).message}`);
          // eslint-disable-next-line no-console
          console.error("[CollocationNetwork] load failed:", e);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cid, centerNode, level, win, minFreq, buildGraph, flashMsg]);

  // ── Sigma lifecycle (created once per mount) ────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const graph = graphRef.current ?? new Graph();
    graphRef.current = graph;

    const renderer = new Sigma(graph, container, {
      allowInvalidContainer: true,
      renderEdgeLabels: false,
      labelRenderedSizeThreshold: 0.1,
      labelColor: { color: "#1f2d28" },
      labelSize: 12,
      labelWeight: "500",
      defaultEdgeColor: BRAND_EDGE,
      minCameraRatio: 0.08,
      maxCameraRatio: 12,
    });
    sigmaRef.current = renderer;

    // Node reducer — color by role, hover ring, drag highlight.
    renderer.setSetting("nodeReducer", (node, data: Attributes) => {
      const res: Attributes = { ...data, forceLabel: true };
      if (data.isCenter) {
        res.color = BRAND;
        res.zIndex = 10;
      } else {
        res.color = BRAND_NODE;
      }
      if (hoverRef.current === node || draggingRef.current === node) {
        res.color = HIGHLIGHT;
        res.size = (data.size ?? 6) + 2.5;
        res.zIndex = 20;
      }
      return res;
    });

    // Edge reducer — thickness ∝ selected measure, hover emphasis.
    // v1.0.7 fix: this reducer MUST read the graph through the renderer.
    // The previous version closed over the empty graph instance created at
    // mount time, so after the data effect called setGraph() with the real
    // graph, graph.extremities(edge) threw NotFoundGraphError for every edge,
    // aborting Sigma's re-index mid-refresh and leaving the canvas blank
    // forever (the error was then swallowed by the fetch's catch block).
    renderer.setSetting("edgeReducer", (edge, data: Attributes) => {
      const res: Attributes = { ...data };
      const norms = (data.norms ?? {}) as Record<string, number>;
      const norm = norms[measureRef.current] ?? 0;
      res.size = 0.4 + 3.2 * norm;
      res.color = BRAND_EDGE;
      const g = renderer.getGraph();
      if (g.hasEdge(edge)) {
        const [s, t] = g.extremities(edge);
        if (hoverRef.current && (hoverRef.current === s || hoverRef.current === t)) {
          res.color = HIGHLIGHT;
          res.size += 1.2;
          res.zIndex = 5;
        }
      }
      return res;
    });

    // ── Drag nodes (sigma v3 pattern) ──
    renderer.on("downNode", (e) => {
      draggingRef.current = e.node;
      renderer.getGraph().setNodeAttribute(e.node, "highlighted", true);
    });
    renderer.getMouseCaptor().on("mousemovebody", (e) => {
      if (!draggingRef.current) return;
      const pos = renderer.viewportToGraph(e);
      const g = renderer.getGraph();
      g.setNodeAttribute(draggingRef.current, "x", pos.x);
      g.setNodeAttribute(draggingRef.current, "y", pos.y);
      e.preventSigmaDefault?.();
      (e.original as unknown as { preventDefault?: () => void })?.preventDefault?.();
      (e.original as unknown as { stopPropagation?: () => void })?.stopPropagation?.();
    });
    renderer.getMouseCaptor().on("mouseup", () => {
      if (draggingRef.current) {
        renderer.getGraph().setNodeAttribute(draggingRef.current, "highlighted", false);
        draggingRef.current = null;
      }
    });

    // ── Hover tooltip with exact statistics ──
    renderer.on("enterNode", (e) => {
      hoverRef.current = e.node;
      const g = renderer.getGraph();
      const attrs = g.getNodeAttributes(e.node);
      const parts = [
        `${e.node}${attrs.isCenter ? " — center" : ""}`,
        `corpus freq: ${attrs.freq ?? "—"}`,
        `collocates in graph: ${g.degree(e.node)}`,
      ];
      // Strongest incident edge, with the exact numbers for every measure.
      let bestEdge: CollocationNetworkEdge | null = null;
      g.forEachEdge(e.node, (_e, attr, _s, _t) => {
        const edge = attr as CollocationNetworkEdge & { norms?: Record<string, number> };
        const v = Math.abs(Number(edge[measureRef.current] ?? 0));
        if (!bestEdge || v > Math.abs(Number(bestEdge[measureRef.current] ?? 0))) {
          bestEdge = edge;
        }
      });
      if (bestEdge) {
        const edge = bestEdge as CollocationNetworkEdge;
        parts.push(
          `with “${edge.source === e.node ? edge.target : edge.source}”: O=${edge.O}, f(x)=${edge.fx}, f(y)=${edge.fy}`,
        );
        for (const m of MEASURES) {
          const v = edge[m.key];
          if (typeof v === "number") parts.push(`${m.label}: ${v}`);
        }
      }
      const p = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
      const rect = container.getBoundingClientRect();
      setTooltip({ x: p.x + rect.left + 14, y: p.y + rect.top - 8, text: parts.join("\n") });
    });
    renderer.on("leaveNode", () => {
      hoverRef.current = null;
      setTooltip(null);
    });

    // Right-click anywhere in the container → custom menu, no browser menu.
    const blockMenu = (e: MouseEvent) => e.preventDefault();
    container.addEventListener("contextmenu", blockMenu);

    return () => {
      container.removeEventListener("contextmenu", blockMenu);
      renderer.kill();
      sigmaRef.current = null;
    };
  }, []);

  // Keep measure changes in sync without refetching.
  useEffect(() => {
    measureRef.current = measure;
    sigmaRef.current?.refresh();
  }, [measure]);

  // ── Expand / collapse ───────────────────────────────────────────────────
  const expandNode = useCallback(
    async (node: string) => {
      const graph = graphRef.current;
      if (!graph || graph.order >= MAX_NODES) {
        flashMsg(`Node budget reached (${MAX_NODES}). Right-click a word to re-center instead.`);
        return;
      }
      try {
        const res = await api.collocationNetworkExpand(cid, {
          node,
          level,
          window: win,
          min_freq: minFreq,
          measure: "mi",
          top_n: EXPAND_TOP_N,
          depth: 2,
          known_nodes: graph.nodes(),
        });
        const added: string[] = [];
        const maxFreq = Math.max(...res.nodes.map((n) => n.freq), 1);
        const px = graph.getNodeAttribute(node, "x");
        const py = graph.getNodeAttribute(node, "y");
        res.nodes.forEach((n, i) => {
          if (graph.hasNode(n.id) || n.id === node) return;
          const angle = (2 * Math.PI * i) / Math.max(res.nodes.length, 3);
          graph.addNode(n.id, {
            freq: n.freq,
            degree: n.degree,
            strength: n.strength,
            isCenter: false,
            size: 5 + 9 * Math.sqrt(n.freq / maxFreq),
            label: n.id,
            parent: node,
            x: px + Math.cos(angle) * 0.35,
            y: py + Math.sin(angle) * 0.35,
          });
          added.push(n.id);
        });
        for (const edge of res.edges) {
          if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
          if (graph.hasEdge(edge.source, edge.target)) continue;
          graph.addEdge(edge.source, edge.target, {
            ...edge,
            norms: normalizeEdge(edge, res.edges),
          });
        }
        runLayout(graph, 60);
        sigmaRef.current?.refresh();
        setExpanded((prev) => new Set(prev).add(node));
        setStats((s) => ({ ...s, nodes: graph.order, edges: graph.size }));
        if (added.length === 0) flashMsg(`“${node}” has no new collocates to add.`);
        void qc; // query client reserved for caching expansions later
      } catch (e) {
        flashMsg(`Expansion failed: ${(e as Error).message}`);
      }
    },
    [cid, level, win, minFreq, flashMsg, qc],
  );

  const collapseNode = useCallback(
    (node: string) => {
      const graph = graphRef.current;
      if (!graph) return;
      // Remove the whole subtree below `node` (parent links), keeping the
      // pivot itself. Nodes the user manually dragged stay — they are still
      // parented, so they go too; re-expanding is one click away.
      const doomed = new Set<string>();
      let frontier = [node];
      while (frontier.length) {
        const next: string[] = [];
        graph.forEachNode((n, attrs) => {
          if (attrs.isCenter || doomed.has(n)) return;
          if (attrs.parent && frontier.includes(attrs.parent as string)) {
            doomed.add(n);
            next.push(n);
          }
        });
        frontier = next;
      }
      for (const n of doomed) graph.dropNode(n);
      sigmaRef.current?.refresh();
      setExpanded((prev) => {
        const next = new Set(prev);
        for (const n of doomed) next.delete(n);
        next.delete(node);
        return next;
      });
      setStats((s) => ({ ...s, nodes: graph.order, edges: graph.size }));
    },
    [],
  );

  const handleNodeClick = useCallback(
    (node: string) => {
      const graph = graphRef.current;
      if (!graph) return;
      if (graph.getNodeAttribute(node, "isCenter")) return;
      if (expanded.has(node)) collapseNode(node);
      else void expandNode(node);
    },
    [expanded, expandNode, collapseNode],
  );

  // Click wiring (kept outside the one-time Sigma effect so `expanded`
  // state stays fresh without re-creating the renderer).
  useEffect(() => {
    const renderer = sigmaRef.current;
    if (!renderer) return;
    const onClick = (e: { node: string }) => handleNodeClick(e.node);
    const onRightClick = (e: { node: string }) => {
      if (!graphRef.current?.getNodeAttribute(e.node, "isCenter")) {
        onSetCenter?.(e.node);
      }
    };
    renderer.on("clickNode", onClick);
    renderer.on("rightClickNode", onRightClick);
    return () => {
      renderer.off("clickNode", onClick);
      renderer.off("rightClickNode", onRightClick);
    };
  }, [handleNodeClick, onSetCenter]);

  // ── Toolbar actions ─────────────────────────────────────────────────────
  const resetLayout = () => {
    const graph = graphRef.current;
    if (!graph) return;
    runLayout(graph, 140);
    sigmaRef.current?.refresh();
  };

  const recenterView = () => {
    sigmaRef.current?.getCamera().animatedReset({ duration: 300 });
  };

  const exportPng = () => {
    const container = containerRef.current;
    const renderer = sigmaRef.current;
    if (!container || !renderer) return;
    renderer.refresh();
    const canvases = Array.from(container.querySelectorAll("canvas"));
    if (canvases.length === 0) return;
    const out = document.createElement("canvas");
    out.width = canvases[0].width;
    out.height = canvases[0].height;
    const ctx = out.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, out.width, out.height);
    for (const c of canvases) ctx.drawImage(c, 0, 0);
    out.toBlob((blob) => {
      if (blob) void downloadBlob(blob, `collocation_network_${centerNode}.png`);
    }, "image/png");
  };

  const exportJson = () => {
    const graph = graphRef.current;
    if (!graph) return;
    const payload = {
      params: { corpus_id: cid, node: centerNode, level, window: win, min_freq: minFreq },
      measure: measure,
      stats,
      nodes: graph.mapNodes((id, attrs) => ({ id, ...attrs })),
      edges: graph.mapEdges((_e, attrs, s, t) => ({ source: s, target: t, ...attrs })),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    void downloadBlob(blob, `collocation_network_${centerNode}.json`);
  };

  const total = useMemo(() => stats, [stats]);

  return (
    <div className="collocation-3d-network">
      <div className="network-header">
        <h4 className="network-title">Collocation Network</h4>
        <div className="network-controls">
          <label className="network-measure-label">
            Measure
            <select
              value={measure}
              onChange={(e) => setMeasure(e.target.value as CollocationMeasure)}
              className="network-measure-select"
            >
              {MEASURES.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <span className={total.nodes >= MAX_NODES ? "network-stats warn" : "network-stats"}>
            {total.nodes} nodes · {total.edges} edges · density {total.density.toFixed(3)}
          </span>
          <button className="btn-small" onClick={resetLayout} title="Re-run the ForceAtlas2 layout">
            Re-layout
          </button>
          <button className="btn-small" onClick={recenterView} title="Reset the camera">
            Fit view
          </button>
          <button className="btn-small" onClick={exportPng} title="Save the current view as PNG">
            Export PNG
          </button>
          <button className="btn-small" onClick={exportJson} title="Save the full graph (positions + all statistics) as JSON">
            Export JSON
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="network-canvas"
        role="application"
        aria-label={`Interactive collocation network for '${centerNode}'. Click a collocate to expand its collocates. The table above shows the same data in text form.`}
      />

      {flash && <div className="network-flash">{flash}</div>}

      {loadError && !flash && (
        <div className="network-flash" role="alert" style={{ background: "var(--danger, #b3261e)" }}>
          {loadError}
        </div>
      )}

      {empty && !flash && !loadError && (
        <div className="network-flash">No collocates met the thresholds — try a lower min frequency.</div>
      )}

      {tooltip && (
        <div className="network-tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
          {tooltip.text.split("\n").map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}

      <p className="network-hint">
        Click a collocate to expand its collocates · click again to collapse · right-click to set
        as center · drag nodes to rearrange · scroll to zoom. Edge thickness = the selected measure;
        node size = corpus frequency. Switching the measure re-weights every edge instantly (no
        refetch, ±{win} words, min freq {minFreq}).
      </p>
    </div>
  );
}

/**
 * Precompute per-measure normalized scores (0..1) for one edge against the
 * whole edge set, so the edge reducer can re-weight instantly when the user
 * switches measures.
 */
function normalizeEdge(edge: CollocationNetworkEdge, all: CollocationNetworkEdge[]): Record<string, number> {
  const norms: Record<string, number> = {};
  for (const m of MEASURES) {
    const v = Math.abs(Number(edge[m.key] ?? 0));
    const max = Math.max(...all.map((e) => Math.abs(Number(e[m.key] ?? 0))), 1e-12);
    norms[m.key] = max > 0 ? v / max : 0;
  }
  return norms;
}
