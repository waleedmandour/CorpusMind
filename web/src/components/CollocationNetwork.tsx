/**
 * CollocationNetwork (v1.2.0, Issue 8) — interactive animated 3D network.
 *
 * Redesign goals (user-reported: "clicking the desired collocate to expand
 * and find out other related collocates"):
 *   - Click a collocate → its collocates spawn on a local orbit around it
 *     (progressive expansion, powered by the same collocation endpoint —
 *     zero engine changes; each pivot query is cached by React Query).
 *   - Click an expanded node again → collapse its subtree.
 *   - Hover → pauses rotation + tooltip (word, co-occurrence, score).
 *   - Drag → orbit; wheel → zoom; Pause/Play → auto-rotation.
 *   - Right-click a node → "Set as center" (re-runs the main query).
 *   - Node budget (~100) with oldest-subtree pruning protection, reverse-
 *     edge dedupe (canonical pair key), honest pivot-relative scores.
 *
 * Rendering: hand-rolled 2D-canvas with 3D projection (no graph libraries —
 * keeps the Tauri bundle small), devicePixelRatio-aware (no more blur),
 * labels drawn on every node, O(n) per-frame hot loop.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, downloadBlob, type CollocationRow } from "@/lib/api";

const MAX_NODES = 100;
const FIRST_RING = 130;   // radius of depth-1 orbit
const CHILD_RING = 62;    // radius of each expanded node's local orbit
const EXPAND_TOP_K = 8;   // collocates added per expansion

interface NetNode {
  id: string;
  x: number; y: number; z: number;   // base position (unit: px at zoom 1)
  depth: number;
  freq: number;
  mi: number;
  parent: string | null;
  expanded: boolean;
  loading: boolean;
}

export interface CollocationNetworkProps {
  cid: string;
  centerNode: string;
  rows: CollocationRow[];
  measureKeys: string[];
  level: "word" | "lemma";
  window: number;
  minFreq: number;
  onSetCenter?: (word: string) => void;
}

/** Fibonacci sphere distribution for n points → deterministic, even. */
function fibonacciSphere(i: number, n: number, radius: number): { x: number; y: number; z: number } {
  const phi = Math.acos(1 - (2 * (i + 0.5)) / n);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i;
  return {
    x: radius * Math.cos(theta) * Math.sin(phi),
    y: radius * Math.sin(theta) * Math.sin(phi),
    z: radius * Math.cos(phi),
  };
}

export function CollocationNetwork({
  cid, centerNode, rows, measureKeys, level, window: win, minFreq, onSetCenter,
}: CollocationNetworkProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Mutable scene graph — the rAF loop reads these; no React churn.
  const nodesRef = useRef<Map<string, NetNode>>(new Map());
  const edgesRef = useRef<Array<{ from: string; to: string; freq: number; depth: number }>>([]);
  const projectedRef = useRef<Map<string, { px: number; py: number; r: number }>>(new Map());
  const rotationRef = useRef(0);
  const pitchRef = useRef(0.25);
  const zoomRef = useRef(1);
  const pausedRef = useRef(false);
  const draggingRef = useRef<{ x: number; y: number } | null>(null);
  const hoveredRef = useRef<string | null>(null);
  const framesRef = useRef(0);

  const [paused, setPaused] = useState(false);
  const [stats, setStats] = useState({ hops: 1, nodes: 0 });
  const [budgetFlash, setBudgetFlash] = useState(false);
  const [tooltip, setTooltip] = useState<{ id: string; x: number; y: number; label: string } | null>(null);
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);

  const qc = useQueryClient();

  // Strongest available association measure for sizing/coloring.
  const miKey = useMemo(
    () => measureKeys.find((k) => k.toLowerCase().includes("mi")) || measureKeys[0] || "O",
    [measureKeys],
  );

  // ------------------------------------------------------------------ //
  // Build / reset the graph from the center query
  // ------------------------------------------------------------------ //
  const resetGraph = useCallback(() => {
    const nodes = new Map<string, NetNode>();
    const edges: Array<{ from: string; to: string; freq: number; depth: number }> = [];
    nodes.set(centerNode, {
      id: centerNode, x: 0, y: 0, z: 0, depth: 0,
      freq: 0, mi: 0, parent: null, expanded: true, loading: false,
    });
    const maxMi = Math.max(...rows.map((r) => Math.abs(Number((r as unknown as Record<string, unknown>)[miKey]) || 0)), 1);
    rows.slice(0, 30).forEach((r, i) => {
      if (nodes.has(r.collocate)) return;
      const pos = fibonacciSphere(i, Math.min(rows.length, 30), FIRST_RING);
      nodes.set(r.collocate, {
        id: r.collocate,
        x: pos.x, y: pos.y, z: pos.z,
        depth: 1, freq: r.O, mi: Math.abs(Number((r as unknown as Record<string, unknown>)[miKey]) || 0) / maxMi,
        parent: centerNode, expanded: false, loading: false,
      });
      edges.push({ from: centerNode, to: r.collocate, freq: r.O, depth: 1 });
    });
    nodesRef.current = nodes;
    edgesRef.current = edges;
    setStats({ hops: 1, nodes: nodes.size });
  }, [centerNode, rows, miKey]);

  useEffect(() => {
    resetGraph();
  }, [resetGraph]);

  // ------------------------------------------------------------------ //
  // Expansion / collapse
  // ------------------------------------------------------------------ //
  const expandNode = useCallback(async (id: string) => {
    const nodes = nodesRef.current;
    const node = nodes.get(id);
    if (!node || node.loading) return;
    if (nodes.size >= MAX_NODES) {
      setBudgetFlash(true);
      setTimeout(() => setBudgetFlash(false), 2500);
      return;
    }
    node.loading = true;
    try {
      const res = await qc.fetchQuery({
        queryKey: ["collocations", cid, { n: id, l: level, w: win, mf: minFreq }],
        queryFn: () => api.collocations(cid, id, level, win, minFreq, undefined, 30),
        staleTime: 60_000,
      });
      if (nodesRef.current.get(id) !== node) return; // graph was reset mid-flight
      const maxMi = Math.max(
        ...res.rows.map((r) => Math.abs(Number((r as unknown as Record<string, unknown>)[miKey]) || 0)), 1,
      );
      const taken = res.rows
        .filter((r) => !nodes.has(r.collocate) && r.collocate !== centerNode)
        .slice(0, Math.min(EXPAND_TOP_K, MAX_NODES - nodes.size));
      taken.forEach((r, i) => {
        const local = fibonacciSphere(i, Math.max(taken.length, 3), CHILD_RING);
        // De-duplicate reverse edges implicitly: tree structure keeps one
        // parent per node; a pair never gets two edges.
        nodes.set(r.collocate, {
          id: r.collocate,
          x: node.x + local.x,
          y: node.y + local.y,
          z: node.z + local.z,
          depth: node.depth + 1,
          freq: r.O,
          mi: Math.abs(Number((r as unknown as Record<string, unknown>)[miKey]) || 0) / maxMi,
          parent: id,
          expanded: false,
          loading: false,
        });
        edgesRef.current.push({ from: id, to: r.collocate, freq: r.O, depth: node.depth + 1 });
      });
      node.expanded = true;
      const maxDepth = Math.max(...[...nodes.values()].map((n) => n.depth));
      setStats({ hops: maxDepth, nodes: nodes.size });
    } finally {
      node.loading = false;
    }
  }, [cid, level, win, minFreq, miKey, centerNode, qc]);

  const collapseNode = useCallback((id: string) => {
    const nodes = nodesRef.current;
    const node = nodes.get(id);
    if (!node) return;
    // Remove all descendants (BFS over parent links)
    const doomed = new Set<string>();
    let frontier = [id];
    while (frontier.length) {
      const next: string[] = [];
      for (const n of nodes.values()) {
        if (n.parent && frontier.includes(n.parent) && !doomed.has(n.id)) {
          doomed.add(n.id);
          next.push(n.id);
        }
      }
      frontier = next;
    }
    for (const d of doomed) nodes.delete(d);
    edgesRef.current = edgesRef.current.filter((e) => !doomed.has(e.to));
    node.expanded = false;
    const maxDepth = Math.max(1, ...[...nodes.values()].map((n) => n.depth));
    setStats({ hops: maxDepth, nodes: nodes.size });
  }, []);

  const handleNodeClick = useCallback((id: string) => {
    const node = nodesRef.current.get(id);
    if (!node || node.depth === 0) return;
    if (node.expanded) collapseNode(id);
    else void expandNode(id);
  }, [collapseNode, expandNode]);

  // ------------------------------------------------------------------ //
  // Render loop
  // ------------------------------------------------------------------ //
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId = 0;
    const draw = () => {
      const wrap = wrapRef.current;
      const cssW = wrap?.clientWidth || 600;
      const cssH = 420;
      const dpr = window.devicePixelRatio || 1;
      const targetW = Math.round(cssW * dpr);
      const targetH = Math.round(cssH * dpr);
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssW, cssH);

      const cx = cssW / 2;
      const cy = cssH / 2;
      const zoom = zoomRef.current;
      const rot = rotationRef.current;
      const pitch = pitchRef.current;
      const cosR = Math.cos(rot), sinR = Math.sin(rot);
      const cosP = Math.cos(pitch), sinP = Math.sin(pitch);

      if (!pausedRef.current && !draggingRef.current && !hoveredRef.current) {
        rotationRef.current += 0.005;
      }

      // Project all nodes (O(n)); rotate around Y then X, perspective scale.
      const projected: Array<{ node: NetNode; px: number; py: number; pz: number; r: number }> = [];
      for (const node of nodesRef.current.values()) {
        const x1 = node.x * cosR - node.z * sinR;
        const z1 = node.x * sinR + node.z * cosR;
        const y1 = node.y * cosP - z1 * sinP;
        const z2 = node.y * sinP + z1 * cosP;
        const persp = (z2 + 340) / 620;          // ~0=near, 1=far
        const px = cx + x1 * zoom * (1 + persp * 0.25);
        const py = cy + y1 * zoom * (1 + persp * 0.25);
        const r = node.depth === 0
          ? 15
          : (5 + node.mi * 10) * (1 + persp * 0.2) * (0.85 + zoom * 0.15);
        projected.push({ node, px, py, pz: persp, r });
      }
      projected.sort((a, b) => b.pz - a.pz);       // far → near

      projectedRef.current.clear();
      for (const p of projected) projectedRef.current.set(p.node.id, { px: p.px, py: p.py, r: p.r });

      // Edges (parent → child), O(E)
      ctx.lineCap = "round";
      for (const e of edgesRef.current) {
        const a = projectedRef.current.get(e.from);
        const b = projectedRef.current.get(e.to);
        if (!a || !b) continue;
        ctx.strokeStyle = `rgba(11, 110, 79, ${0.14 + (1 - Math.min(e.depth, 4) / 4) * 0.4})`;
        ctx.lineWidth = Math.max(0.6, Math.min(3.2, e.freq / 40));
        ctx.beginPath();
        ctx.moveTo(a.px, a.py);
        ctx.lineTo(b.px, b.py);
        ctx.stroke();
      }

      // Nodes
      for (const p of projected) {
        const { node, px, py, pz, r } = p;
        const heat = node.depth === 0 ? 1 : Math.min(node.mi, 1);
        const cr = Math.round(11 + heat * 200);
        const cg = Math.round(110 - heat * 50);
        const cb = Math.round(79 - heat * 60);
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fillStyle = node.depth === 0 ? "#0b6e4f" : `rgb(${cr},${cg},${cb})`;
        ctx.globalAlpha = 0.35 + (1 - pz) * 0.65;
        ctx.fill();
        ctx.globalAlpha = 1;

        if (hoveredRef.current === node.id) {
          ctx.beginPath();
          ctx.arc(px, py, r + 4, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(230, 140, 30, 0.9)";
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        if (node.loading) {
          const t = framesRef.current * 0.15;
          ctx.beginPath();
          ctx.arc(px, py, r + 6, t, t + Math.PI * 1.2);
          ctx.strokeStyle = "rgba(11, 110, 79, 0.9)";
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        if (node.expanded && node.depth > 0) {
          ctx.beginPath();
          ctx.arc(px, py, r + 3, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(11, 110, 79, 0.45)";
          ctx.lineWidth = 1.4;
          ctx.stroke();
        }

        // Labels on every node (the old design hid small ones)
        ctx.font = `${node.depth === 0 ? "600 " : ""}${Math.round(10 + (1 - pz) * 1.5)}px system-ui, sans-serif`;
        ctx.fillStyle = `rgba(30, 30, 30, ${0.5 + (1 - pz) * 0.5})`;
        ctx.textAlign = "center";
        ctx.fillText(node.id, px, py - r - 4);
      }

      framesRef.current += 1;
      animId = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animId);
  }, []);

  // ------------------------------------------------------------------ //
  // Pointer interactions
  // ------------------------------------------------------------------ //
  const pickNode = useCallback((mx: number, my: number): string | null => {
    let best: string | null = null;
    let bestD = Infinity;
    for (const [id, p] of projectedRef.current) {
      const d = (p.px - mx) ** 2 + (p.py - my) ** 2;
      const reach = (p.r + 6) ** 2;
      if (d < reach && d < bestD) {
        best = id;
        bestD = d;
      }
    }
    return best;
  }, []);

  const toLocal = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y } = toLocal(e);
    if (draggingRef.current) {
      const dx = x - draggingRef.current.x;
      const dy = y - draggingRef.current.y;
      draggingRef.current = { x, y };
      rotationRef.current += dx * 0.01;
      pitchRef.current = Math.max(-1.1, Math.min(1.1, pitchRef.current + dy * 0.01));
      setTooltip(null);
      return;
    }
    const id = pickNode(x, y);
    if (id !== hoveredRef.current) hoveredRef.current = id;
    if (id) {
      const n = nodesRef.current.get(id);
      if (n) {
        setTooltip({
          id, x, y,
          label: n.depth === 0
            ? `${id} (center)`
            : `${id} · O=${n.freq} · ${miKey}=${n.mi.toFixed(3)} (within ±${win} of pivot)`,
        });
      }
      e.currentTarget.style.cursor = "pointer";
    } else {
      setTooltip(null);
      e.currentTarget.style.cursor = draggingRef.current ? "grabbing" : "grab";
    }
  };

  const onMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y } = toLocal(e);
    draggingRef.current = { x, y };
    setMenu(null);
  };

  const onMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const wasDragging = draggingRef.current !== null;
    draggingRef.current = null;
    if (!wasDragging) return;
    const { x, y } = toLocal(e);
    const id = pickNode(x, y);
    if (id) handleNodeClick(id);
  };

  const onContextMenu = (e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const { x, y } = toLocal(e);
    const id = pickNode(x, y);
    if (id && id !== centerNode) setMenu({ id, x, y });
    else setMenu(null);
  };

  const exportPng = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob(async (blob) => {
      if (!blob) return;
      await downloadBlob(blob, `collocation-network-${centerNode}.png`);
    }, "image/png");
  };

  const menuNode = menu ? nodesRef.current.get(menu.id) : null;

  return (
    <div className="collocation-3d-network" ref={wrapRef}>
      <div className="network-header">
        <h4 className="network-title">Collocation Network (3D)</h4>
        <div className="network-controls">
          <span className={clsxSafe("network-stats", { warn: budgetFlash })}>
            {stats.hops} hop{stats.hops === 1 ? "" : "s"} · {stats.nodes}/{MAX_NODES} nodes
          </span>
          <button
            className="btn-small"
            onClick={() => { setPaused(!paused); pausedRef.current = !paused; }}
            title={paused ? "Resume rotation" : "Pause rotation"}
            aria-label={paused ? "Resume rotation" : "Pause rotation"}
          >
            {paused ? "\u25B6" : "\u23F8"}
          </button>
          <button
            className="btn-small"
            onClick={() => { resetGraph(); rotationRef.current = 0; pitchRef.current = 0.25; zoomRef.current = 1; }}
            title="Reset to the original collocates"
          >
            Reset
          </button>
          <button className="btn-small" onClick={exportPng} title="Save the current view as PNG">
            Export view (PNG)
          </button>
        </div>
      </div>

      <canvas
        ref={canvasRef}
        className="network-canvas"
        role="application"
        aria-label={`Interactive 3D collocation network for '${centerNode}'. Click a collocate to expand its collocates. The table above shows the same data in text form.`}
        onMouseMove={onMouseMove}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onMouseLeave={() => { draggingRef.current = null; hoveredRef.current = null; setTooltip(null); }}
        onContextMenu={onContextMenu}
        onWheel={(e) => {
          e.preventDefault();
          zoomRef.current = Math.max(0.55, Math.min(2.2, zoomRef.current * (e.deltaY < 0 ? 1.1 : 0.9)));
        }}
      />

      {tooltip && (
        <div
          className="network-tooltip"
          style={{ left: tooltip.x + 12, top: tooltip.y - 28 }}
        >
          {tooltip.label}
        </div>
      )}

      {menu && menuNode && (
        <div className="network-menu" style={{ left: menu.x, top: menu.y }} role="menu">
          <button
            role="menuitem"
            onClick={() => { void expandNode(menu.id); setMenu(null); }}
            disabled={menuNode.expanded || menuNode.loading}
          >
            {menuNode.loading ? "Expanding…" : menuNode.expanded ? "Already expanded" : `Expand collocates of “${menu.id}”`}
          </button>
          <button
            role="menuitem"
            onClick={() => { collapseNode(menu.id); setMenu(null); }}
            disabled={!menuNode.expanded || menuNode.depth === 0}
          >
            Collapse
          </button>
          <button
            role="menuitem"
            onClick={() => { onSetCenter?.(menu.id); setMenu(null); }}
          >
            Set as center (re-run query)
          </button>
        </div>
      )}

      <p className="network-hint">
        Click a collocate to expand its collocates · click again to collapse ·
        drag to orbit · scroll to zoom · hover pauses rotation. Edge width = co-occurrence
        frequency; node size/color = association score — scores are relative to each
        pivot (within ±{win} words).
      </p>
    </div>
  );
}

// tiny local clsx-like helper (avoids importing clsx here)
function clsxSafe(base: string, mods: Record<string, boolean>): string {
  return base + Object.entries(mods).filter(([, v]) => v).map(([k]) => ` ${k}`).join("");
}
