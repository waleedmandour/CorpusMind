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

/**
 * Sigma v3 is WebGL2-only. Some desktop webviews (WebKitGTK on Linux without
 * compositing, remote desktops / VMs without a GPU, some locked-down
 * WebView2 installs) silently return a context that can't actually draw —
 * `new Sigma()` doesn't always throw in that case, it just produces an empty
 * canvas forever. Probe WebGL2 up front so we can route to the built-in
 * 2D-canvas fallback instead of leaving the user with a blank box and no
 * way to explain why.
 *
 * Manual override for diagnostics: localStorage["cm-network-renderer"] =
 * "canvas" forces the 2D engine, "webgl" forces Sigma.
 */
function supportsWebGL2(): boolean {
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2");
    return !!gl;
  } catch {
    return false;
  }
}

type NetworkRendererMode = "webgl" | "canvas2d";

function getPreferredRendererMode(): NetworkRendererMode {
  try {
    const override = localStorage.getItem("cm-network-renderer");
    if (override === "canvas") return "canvas2d";
    if (override === "webgl") return "webgl";
  } catch {
    /* storage unavailable (e.g. hardened private mode) — use detection */
  }
  return supportsWebGL2() ? "webgl" : "canvas2d";
}

/** Shared hover-tooltip text (used by both the WebGL and 2D renderers). */
function nodeTooltipText(g: Graph, node: string, measure: CollocationMeasure): string {
  const attrs = g.getNodeAttributes(node);
  const parts = [
    `${node}${attrs.isCenter ? " — center" : ""}`,
    `corpus freq: ${attrs.freq ?? "—"}`,
    `collocates in graph: ${g.degree(node)}`,
  ];
  // Strongest incident edge, with the exact numbers for every measure.
  let bestEdge: CollocationNetworkEdge | null = null;
  g.forEachEdge(node, (_e, attr, _s, _t) => {
    const edge = attr as CollocationNetworkEdge & { norms?: Record<string, number> };
    const v = Math.abs(Number(edge[measure] ?? 0));
    if (!bestEdge || v > Math.abs(Number(bestEdge[measure] ?? 0))) {
      bestEdge = edge;
    }
  });
  if (bestEdge) {
    const edge = bestEdge as CollocationNetworkEdge;
    parts.push(
      `with “${edge.source === node ? edge.target : edge.source}”: O=${edge.O}, f(x)=${edge.fx}, f(y)=${edge.fy}`,
    );
    for (const m of MEASURES) {
      const v = edge[m.key];
      if (typeof v === "number") parts.push(`${m.label}: ${v}`);
    }
  }
  return parts.join("\n");
}

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
  // v1.0.8: renderer selection. Sigma v3 needs a working WebGL2 context; when
  // that is missing (VMs, remote-desktop sessions, disabled hardware
  // acceleration, locked-down webviews) or Sigma fails to start, we render
  // the SAME graph with a built-in 2D-canvas engine instead of a blank box.
  // localStorage["cm-network-renderer"] = "canvas" | "webgl" forces a mode.
  const [mode, setMode] = useState<NetworkRendererMode>(getPreferredRendererMode);
  const modeRef = useRef<NetworkRendererMode>(mode);
  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);
  // Redraw tick for the 2D fallback — mirrors every sigmaRef.refresh() call.
  const [tick, setTick] = useState(0);
  const [fitTick, setFitTick] = useState(0);

  const refreshAll = useCallback(() => {
    if (modeRef.current === "webgl") sigmaRef.current?.refresh();
    else setTick((t) => t + 1);
  }, []);

  const switchToCanvas2D = useCallback((reason: string) => {
    if (modeRef.current === "canvas2d") return;
    // eslint-disable-next-line no-console
    console.warn(`[CollocationNetwork] switching to 2D canvas renderer: ${reason}`);
    modeRef.current = "canvas2d";
    setMode("canvas2d");
  }, []);

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
          refreshAll();
          setStats({ nodes: 0, edges: 0, density: 0 });
          setEmpty(true);
          return;
        }
        graphRef.current = buildGraph(res);
        setStats(res.stats);
        setExpanded(new Set());
        sigmaRef.current?.setGraph(graphRef.current);
        refreshAll();
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
  }, [cid, centerNode, level, win, minFreq, buildGraph, flashMsg, refreshAll]);

  // ── Sigma lifecycle (WebGL path; created once per mount) ────────────────
  useEffect(() => {
    if (mode !== "webgl") return;
    const container = containerRef.current;
    if (!container) return;

    const graph = graphRef.current ?? new Graph();
    graphRef.current = graph;

    let renderer: Sigma;
    try {
      renderer = new Sigma(graph, container, {
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
    } catch (e) {
      // Never let a renderer-construction failure disappear silently —
      // fall back to the 2D canvas so the network still appears.
      // eslint-disable-next-line no-console
      console.error("[CollocationNetwork] Sigma construction failed:", e);
      switchToCanvas2D(`Sigma failed to start: ${(e as Error).message}`);
      return;
    }
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

    // ── Hover tooltip with exact statistics (shared with the 2D renderer) ──
    renderer.on("enterNode", (e) => {
      hoverRef.current = e.node;
      const g = renderer.getGraph();
      const attrs = g.getNodeAttributes(e.node);
      const p = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
      const rect = container.getBoundingClientRect();
      setTooltip({
        x: p.x + rect.left + 14,
        y: p.y + rect.top - 8,
        text: nodeTooltipText(g, e.node, measureRef.current),
      });
    });
    renderer.on("leaveNode", () => {
      hoverRef.current = null;
      setTooltip(null);
    });

    // Right-click anywhere in the container → custom menu, no browser menu.
    const blockMenu = (e: MouseEvent) => e.preventDefault();
    container.addEventListener("contextmenu", blockMenu);

    // First paint — if the WebGL pipeline is broken in this webview (context
    // created but unable to draw, shader compile failures, …), an exception
    // here is a clear signal to fall back instead of staying blank.
    try {
      renderer.refresh();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[CollocationNetwork] Sigma initial refresh failed:", e);
      switchToCanvas2D(`Sigma refresh failed: ${(e as Error).message}`);
      try {
        renderer.kill();
      } catch {
        /* already dead */
      }
      sigmaRef.current = null;
      container.removeEventListener("contextmenu", blockMenu);
      return;
    }

    // The container is sized in CSS (fixed block-size, 100% inline-size),
    // but if it's mounted before its parent has been laid out (font-load
    // reflow, panel animation) Sigma can start at 0×0 and never repaint on
    // its own. Kick a refresh whenever the observed size actually changes so
    // that case self-heals instead of staying blank.
    let lastW = 0;
    let lastH = 0;
    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      if (Math.abs(width - lastW) > 1 || Math.abs(height - lastH) > 1) {
        lastW = width;
        lastH = height;
        try {
          renderer.refresh();
        } catch {
          /* transient resize during teardown — ignore */
        }
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      container.removeEventListener("contextmenu", blockMenu);
      renderer.kill();
      sigmaRef.current = null;
    };
  }, [mode, switchToCanvas2D]);

  // Keep measure changes in sync without refetching.
  useEffect(() => {
    measureRef.current = measure;
    refreshAll();
  }, [measure, refreshAll]);

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
        refreshAll();
        setExpanded((prev) => new Set(prev).add(node));
        setStats((s) => ({ ...s, nodes: graph.order, edges: graph.size }));
        if (added.length === 0) flashMsg(`“${node}” has no new collocates to add.`);
        void qc; // query client reserved for caching expansions later
      } catch (e) {
        flashMsg(`Expansion failed: ${(e as Error).message}`);
      }
    },
    [cid, level, win, minFreq, flashMsg, qc, refreshAll],
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
      refreshAll();
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

  const handleCanvasRightClick = useCallback(
    (node: string) => {
      if (!graphRef.current?.getNodeAttribute(node, "isCenter")) onSetCenter?.(node);
    },
    [onSetCenter],
  );

  // ── Toolbar actions ─────────────────────────────────────────────────────
  const resetLayout = () => {
    const graph = graphRef.current;
    if (!graph) return;
    runLayout(graph, 140);
    refreshAll();
  };

  const recenterView = () => {
    if (modeRef.current === "webgl") {
      sigmaRef.current?.getCamera().animatedReset({ duration: 300 });
    } else {
      setFitTick((t) => t + 1);
    }
  };

  const exportPng = () => {
    const container = containerRef.current;
    if (!container) return;
    if (modeRef.current === "webgl") {
      const renderer = sigmaRef.current;
      if (!renderer) return;
      renderer.refresh();
    }
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
          {mode === "canvas2d" && (
            <span
              className="network-mode-badge"
              title="WebGL2 is not available in this window — the network is rendered with the built-in 2D canvas engine. Every interaction still works."
            >
              2D mode
            </span>
          )}
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
      >
        {mode === "canvas2d" && (
          <NetworkCanvas2D
            graphRef={graphRef}
            measureRef={measureRef}
            refreshTick={tick}
            fitTick={fitTick}
            onHover={setTooltip}
            onNodeClick={handleNodeClick}
            onNodeRightClick={handleCanvasRightClick}
          />
        )}
      </div>

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
        {mode === "canvas2d"
          ? " Rendered with the built-in 2D engine (no WebGL2 available) — all interactions are identical."
          : ""}
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

// ─────────────────────────────────────────────────────────────────────────────
// NetworkCanvas2D (v1.0.8) — zero-dependency 2D-canvas fallback renderer.
//
// Sigma v3 requires a working WebGL2 context. In webviews without one (VMs,
// remote-desktop sessions, disabled hardware acceleration, locked-down
// installs) the network used to vanish into a permanently blank box. This
// renderer draws the SAME graphology graph — same ForceAtlas2 positions, same
// color system, same per-measure edge weighting — with plain Canvas2D, and
// supports the full interaction set: wheel zoom, drag-pan, node drag, hover
// tooltips, click-to-expand / collapse, right-click re-center. PNG export
// works unchanged (the parent composites whatever <canvas> elements live in
// the container).
// ─────────────────────────────────────────────────────────────────────────────
interface NetworkCanvas2DProps {
  graphRef: { current: Graph | null };
  measureRef: { current: CollocationMeasure };
  refreshTick: number;
  fitTick: number;
  onHover: (t: { x: number; y: number; text: string } | null) => void;
  onNodeClick: (node: string) => void;
  onNodeRightClick: (node: string) => void;
}

function NetworkCanvas2D({
  graphRef,
  measureRef,
  refreshTick,
  fitTick,
  onHover,
  onNodeClick,
  onNodeRightClick,
}: NetworkCanvas2DProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Camera: graph coords → screen via sx = x*scale + tx, sy = ty - y*scale
  // (y flipped so ForceAtlas2 layouts read like Sigma's). fitScale is the
  // scale at the last fit-to-view; node/edge sizes scale with its square root
  // so nodes stay visible when zoomed out and grow gently when zoomed in.
  const viewRef = useRef({ scale: 1, fitScale: 0, tx: 0, ty: 0, fitted: false, lastGraph: null as Graph | null });
  const hoverRef = useRef<string | null>(null);
  const dragRef = useRef<{ node: string | null; panning: boolean; moved: boolean; lastX: number; lastY: number } | null>(
    null,
  );

  const fitView = useCallback(() => {
    const canvas = canvasRef.current;
    const graph = graphRef.current;
    if (!canvas || !graph || graph.order === 0) return;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    graph.forEachNode((_n, a) => {
      minX = Math.min(minX, a.x ?? 0);
      maxX = Math.max(maxX, a.x ?? 0);
      minY = Math.min(minY, a.y ?? 0);
      maxY = Math.max(maxY, a.y ?? 0);
    });
    const pad = 90; // room for node labels
    const spanX = Math.max(maxX - minX, 1e-6);
    const spanY = Math.max(maxY - minY, 1e-6);
    const scale = Math.min(
      Math.max(Math.min((w - pad * 2) / spanX, (h - pad * 2) / spanY), 1e-3),
      4000,
    );
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    viewRef.current = {
      scale,
      fitScale: scale,
      tx: w / 2 - cx * scale,
      ty: h / 2 + cy * scale,
      fitted: true,
      lastGraph: graph,
    };
  }, [graphRef]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const graph = graphRef.current;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    if (w && h) {
      const bw = Math.round(w * dpr);
      const bh = Math.round(h * dpr);
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = bw;
        canvas.height = bh;
        viewRef.current.fitted = false; // geometry changed → re-fit
      }
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!graph || graph.order === 0) return;
    const v = viewRef.current;
    if (!v.fitted || v.lastGraph !== graph) fitView();
    const { scale, tx, ty, fitScale } = viewRef.current;
    const sf = fitScale > 0 ? Math.sqrt(scale / fitScale) : 1;
    const sx = (x: number) => x * scale + tx;
    const sy = (y: number) => ty - y * scale;

    // Hover neighborhood (node ring + incident edges light up, like Sigma).
    const hover = hoverRef.current;
    const hotNodes = new Set<string>();
    if (hover && graph.hasNode(hover)) {
      hotNodes.add(hover);
      graph.forEachEdge(hover, (_e, _a, s, t) => hotNodes.add(s === hover ? t : s));
    }

    // Edges first.
    graph.forEachEdge((_e, attr, s, t) => {
      const a1 = graph.getNodeAttributes(s);
      const a2 = graph.getNodeAttributes(t);
      const norms = (attr.norms ?? {}) as Record<string, number>;
      const norm = norms[measureRef.current] ?? 0;
      const hot = !!hover && (s === hover || t === hover);
      let width = (0.4 + 3.2 * norm) * sf;
      width = Math.min(Math.max(width, 0.35), 16);
      ctx.strokeStyle = hot ? HIGHLIGHT : BRAND_EDGE;
      ctx.lineWidth = hot ? width + 1.2 * sf : width;
      ctx.beginPath();
      ctx.moveTo(sx(a1.x ?? 0), sy(a1.y ?? 0));
      ctx.lineTo(sx(a2.x ?? 0), sy(a2.y ?? 0));
      ctx.stroke();
    });

    // Nodes + labels on top.
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    graph.forEachNode((node, a) => {
      const x = sx(a.x ?? 0);
      const y = sy(a.y ?? 0);
      const r = Math.max((a.size ?? 6) * sf, 2.2);
      const hot = hotNodes.has(node);
      ctx.beginPath();
      ctx.arc(x, y, hot ? r + 2 : r, 0, Math.PI * 2);
      ctx.fillStyle = a.isCenter ? BRAND : hot ? HIGHLIGHT : BRAND_NODE;
      ctx.fill();
      if (a.isCenter) {
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#123528";
        ctx.stroke();
      }
      const label = (a.label ?? node) as string;
      ctx.font = `${a.isCenter ? "600 13px" : "500 12px"} system-ui, -apple-system, 'Segoe UI', sans-serif`;
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
      ctx.strokeText(label, x + r + 5, y);
      ctx.fillStyle = "#1f2d28";
      ctx.fillText(label, x + r + 5, y);
    });
  }, [graphRef, measureRef, fitView]);

  // Interactions (mount-once; handlers read through refs so they stay fresh).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const localPos = (e: MouseEvent) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const hitTest = (mx: number, my: number): string | null => {
      const graph = graphRef.current;
      if (!graph) return null;
      const v = viewRef.current;
      const sf = v.fitScale > 0 ? Math.sqrt(v.scale / v.fitScale) : 1;
      let best: string | null = null;
      let bestD = Infinity;
      graph.forEachNode((node, a) => {
        const x = (a.x ?? 0) * v.scale + v.tx;
        const y = v.ty - (a.y ?? 0) * v.scale;
        const r = Math.max((a.size ?? 6) * sf, 2.2) + 3;
        const d = Math.hypot(mx - x, my - y);
        if (d <= Math.max(r, 7) && d < bestD) {
          best = node;
          bestD = d;
        }
      });
      return best;
    };

    const onDown = (e: MouseEvent) => {
      const p = localPos(e);
      const node = hitTest(p.x, p.y);
      dragRef.current = { node, panning: !node, moved: false, lastX: p.x, lastY: p.y };
      if (node) canvas.style.cursor = "grabbing";
    };
    const onMove = (e: MouseEvent) => {
      const p = localPos(e);
      const drag = dragRef.current;
      const graph = graphRef.current;
      if (drag) {
        if (drag.node && graph) {
          if (Math.abs(p.x - drag.lastX) + Math.abs(p.y - drag.lastY) > 2) drag.moved = true;
          graph.setNodeAttribute(drag.node, "x", (p.x - viewRef.current.tx) / viewRef.current.scale);
          graph.setNodeAttribute(drag.node, "y", (viewRef.current.ty - p.y) / viewRef.current.scale);
          draw();
          return;
        }
        if (drag.panning) {
          viewRef.current.tx += p.x - drag.lastX;
          viewRef.current.ty += p.y - drag.lastY;
          drag.lastX = p.x;
          drag.lastY = p.y;
          draw();
        }
        return;
      }
      const node = hitTest(p.x, p.y);
      if (node !== hoverRef.current) {
        hoverRef.current = node;
        if (node && graph) {
          const r = canvas.getBoundingClientRect();
          onHover({
            x: p.x + r.left + 14,
            y: p.y + r.top - 8,
            text: nodeTooltipText(graph, node, measureRef.current),
          });
        } else {
          onHover(null);
        }
        draw();
      }
    };
    const onUp = () => {
      const drag = dragRef.current;
      dragRef.current = null;
      canvas.style.cursor = "";
      if (drag?.node && !drag.moved) onNodeClick(drag.node);
    };
    const onLeave = () => {
      dragRef.current = null;
      if (hoverRef.current) {
        hoverRef.current = null;
        onHover(null);
        draw();
      }
    };
    const onCtx = (e: MouseEvent) => {
      e.preventDefault();
      const p = localPos(e);
      const node = hitTest(p.x, p.y);
      if (node) onNodeRightClick(node);
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = localPos(e);
      const v = viewRef.current;
      const lo = v.fitScale > 0 ? v.fitScale * 0.05 : 0.01;
      const hi = v.fitScale > 0 ? v.fitScale * 40 : 5000;
      const next = Math.min(Math.max(v.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15), lo), hi);
      const applied = next / v.scale;
      v.tx = p.x - (p.x - v.tx) * applied;
      v.ty = p.y - (p.y - v.ty) * applied;
      v.scale = next;
      draw();
    };

    canvas.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    canvas.addEventListener("mouseleave", onLeave);
    canvas.addEventListener("contextmenu", onCtx);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      canvas.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("mouseleave", onLeave);
      canvas.removeEventListener("contextmenu", onCtx);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [draw, graphRef, measureRef, onHover, onNodeClick, onNodeRightClick]);

  // Size changes (panel reflows, window resizes) → resize + re-fit + redraw.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [draw]);

  useEffect(() => {
    draw();
  }, [refreshTick, draw]);

  useEffect(() => {
    viewRef.current.fitted = false;
    draw();
  }, [fitTick, draw]);

  return <canvas ref={canvasRef} className="network-canvas2d" aria-hidden="true" />;
}
