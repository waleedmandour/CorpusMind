"""Collocation network API — NetworkX-backed graph assembly (v1.2.1).

Powers the interactive Sigma.js collocation-network view. Two endpoints:

  POST /corpora/{cid}/collocations/network          build the local network
  POST /corpora/{cid}/collocations/network/expand   add one pivot's collocates

Graph model
-----------
Nodes  = the node word + its top-N collocates (size ∝ corpus frequency).
Edges  = co-occurrence within the ±window span, carrying ALL association
         measures (MI, T-score, log-likelihood, Dice, LogDice, χ², Delta P)
         so the frontend can re-weight edges without a refetch.

depth=2 additionally meshes the collocates against EACH OTHER: every
collocate gets its own collocation query and any result pointing at a node
already in the graph becomes an edge. That is what makes node degree (and
therefore the layout) genuinely informative — a star graph has nothing to
say. NetworkX provides the graph container, degree/strength computation and
density statistics.

Reproducibility: every response echoes the query parameters (level, window,
min_freq, measure) exactly like the flat collocation table.

v1.2.14 (P1.2):
  - Network endpoints are now wrapped in the shared analysis concurrency
    limiter (`_analysis_semaphore` from engine/api/analysis.py) so they
    share the same 4-slot budget as /collocations and /keyness. Previously
    they bypassed the limiter and could starve other analysis traffic.
  - The depth-2 mesh (per-pivot collocation scans) is now run with
    asyncio.gather and a bounded fan-out of 8 instead of a serial `for`
    loop. With the shipped top_n=14, this collapses 14 serial scans into
    ~2 round-trips.
  - Both endpoints now have an overall 30-second wall-clock deadline
    (asyncio.wait_for). Over-budget requests return 504 with an actionable
    message instead of hanging.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Literal

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from stats.service import compute_collocations
from storage.session import get_session

log = get_logger(__name__)
router = APIRouter()

# v1.2.14 (P1.2): overall wall-clock deadline for a network request. Over-
# budget requests return 504. Env-overridable for classroom deployments
# with larger corpora.
_NETWORK_DEADLINE_S = float(os.environ.get("CORPUSMIND_NETWORK_TIMEOUT_S", "30"))

# Bounded fan-out for the depth-2 per-pivot scan. 8 keeps SQLite page cache
# warm without overwhelming the connection pool.
_FANOUT = 8

# Lazily imported analysis semaphore — kept in engine.api.analysis to share
# the slot budget with /collocations and /keyness.
_analysis_semaphore = None


def _get_analysis_semaphore():
    """Return the shared analysis semaphore, importing lazily to avoid a cycle."""
    global _analysis_semaphore
    if _analysis_semaphore is None:
        try:
            from api.analysis import _analysis_semaphore as sem  # type: ignore
            _analysis_semaphore = sem
        except Exception:
            # If the import fails, fall back to a local 4-slot limiter so
            # the endpoint still functions.
            _analysis_semaphore = asyncio.Semaphore(4)
    return _analysis_semaphore

MEASURES = Literal[
    "mi", "t_score", "log_likelihood", "dice", "log_dice", "chi_square", "delta_p",
    "fisher",
]
_ALL_MEASURE_KEYS = [
    "mi", "t_score", "log_likelihood", "dice", "log_dice", "chi_square", "delta_p",
    "fisher",
]

# stats.service spells delta-p as two directed keys; expose the x→y one as
# the flat "delta_p" edge attribute so the frontend measure selector works.
_DELTA_P_KEY = "delta_p_y_given_x"


def _row_measure(row: dict[str, Any], measure: str) -> float:
    """Value of `measure` for a collocation row (delta_p mapped to x→y).

    Accepts both spellings: raw stats rows carry ``delta_p_y_given_x`` while
    transformed edge attrs carry the flat ``delta_p`` alias.
    """
    if measure == "delta_p":
        for key in ("delta_p_y_given_x", "delta_p"):
            if key in row:
                try:
                    return abs(float(row[key] or 0.0))
                except (TypeError, ValueError):
                    return 0.0
        return 0.0
    try:
        return abs(float(row.get(measure) or 0.0))
    except (TypeError, ValueError):
        return 0.0


class NetworkRequest(BaseModel):
    node: str = Field(..., min_length=1, max_length=100)
    level: Literal["word", "lemma"] = "word"
    window: int = Field(5, ge=1, le=20)
    min_freq: int = Field(3, ge=1)
    measure: MEASURES = "mi"
    top_n: int = Field(14, ge=3, le=30, description="Max collocates of the pivot")
    depth: int = Field(2, ge=1, le=2, description="2 = mesh collocates against each other")
    max_nodes: int = Field(60, ge=5, le=150, description="Safety cap on returned nodes")


class ExpandRequest(NetworkRequest):
    known_nodes: list[str] = Field(
        default_factory=list,
        description="Nodes already in the graph - used to attach mesh edges.",
    )


def _edge_attrs(row: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {"O": row["O"], "fx": row["fx"], "fy": row["fy"], "N": row["N"]}
    for k in _ALL_MEASURE_KEYS:
        if k in row:
            attrs[k] = row[k]
    if _DELTA_P_KEY in row:
        attrs.setdefault("delta_p", row[_DELTA_P_KEY])
    return attrs


async def _pivot_rows(
    session: AsyncSession,
    corpus_id: str,
    pivot: str,
    req: NetworkRequest,
    limit: int,
) -> list[dict[str, Any]]:
    """Collocates of `pivot` sorted by |req.measure| descending."""
    result = await compute_collocations(
        session,
        corpus_id,
        pivot,
        level=req.level,
        window=req.window,
        min_freq=req.min_freq,
        limit=limit,
    )
    rows = list(result.rows)
    rows.sort(key=lambda r: _row_measure(r, req.measure), reverse=True)
    return rows


def _node_payload(node_id: str, freq: int, is_center: bool, G: nx.Graph) -> dict[str, Any]:
    return {
        "id": node_id,
        "freq": freq,
        "degree": int(G.degree(node_id)),
        "strength": float(G.degree(node_id, weight="weight")),
        "is_center": is_center,
    }


def _edge_payload(source: str, target: str, attrs: dict[str, Any]) -> dict[str, Any]:
    out = {"source": source, "target": target}
    out.update(attrs)
    return out


@router.post("/corpora/{cid}/collocations/network")
async def collocation_network(
    cid: str, req: NetworkRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Build the local collocation network for a node word."""
    # v1.2.14 (P1.2): wrap in the shared analysis concurrency limiter so
    # network requests share the 4-slot budget with /collocations and
    # /keyness. Then run under a 30s overall deadline; over-budget -> 504.
    sem = _get_analysis_semaphore()
    try:
        async with sem:
            return await asyncio.wait_for(
                _collocation_network_impl(cid, req, session),
                timeout=_NETWORK_DEADLINE_S,
            )
    except TimeoutError:
        log.warning("collocation_network_timeout", corpus_id=cid, node=req.node,
                     deadline_s=_NETWORK_DEADLINE_S)
        raise HTTPException(
            504,
            detail=(
                f"Collocation network exceeded the {_NETWORK_DEADLINE_S:.0f}s deadline. "
                "Try a smaller top_n, a narrower window, or a more frequent node word."
            ),
        ) from None


async def _collocation_network_impl(
    cid: str, req: NetworkRequest, session: AsyncSession
) -> dict[str, Any]:
    """Inner implementation — separated so the semaphore + deadline wrap it cleanly."""
    try:
        center_rows = await _pivot_rows(session, cid, req.node, req, limit=req.top_n + 10)
    except Exception as e:  # bad corpus id, engine storage errors, …
        log.warning("collocation_network_failed", corpus_id=cid, error=str(e))
        raise HTTPException(400, f"Collocation network failed: {e}") from e

    if not center_rows:
        return {
            "params": req.model_dump(),
            "nodes": [],
            "edges": [],
            "stats": {"nodes": 0, "edges": 0, "density": 0.0},
        }

    G = nx.Graph()
    freq: dict[str, int] = {}
    freq[req.node] = int(center_rows[0].get("fx", 0) or 0)
    G.add_node(req.node)

    top = center_rows[: req.top_n]
    for row in top:
        collocate = row["collocate"]
        attrs = _edge_attrs(row)
        attrs["weight"] = _row_measure(attrs, req.measure)
        freq.setdefault(collocate, int(row.get("fy", 0) or 0))
        if G.has_edge(req.node, collocate):
            continue
        G.add_edge(req.node, collocate, **attrs)

    # depth 2: mesh collocates against each other AND against the center.
    # v1.2.14 (P1.2): parallelise the per-pivot scans with asyncio.gather
    # under a bounded fan-out. The previous serial `for` loop fired 14
    # scans back-to-back; with the v1.2.14 vocab cache (P1.1), the only
    # remaining per-scan cost is the window self-join, which is now bound
    # by fan-out rather than by N.
    if req.depth >= 2:
        async def _mesh_one(pivot: str) -> list[dict[str, Any]]:
            try:
                pivot_result = await compute_collocations(
                    session,
                    cid,
                    pivot,
                    level=req.level,
                    window=req.window,
                    min_freq=req.min_freq,
                    limit=req.top_n * 3,
                )
                return list(pivot_result.rows)
            except Exception as e:
                log.warning(
                    "collocation_network_pivot_failed", pivot=pivot, error=str(e)
                )
                return []

        pivots = [row["collocate"] for row in top]
        # Chunk into _FANOUT batches so we don't open 14 concurrent
        # DB transactions on the same session at once.
        for i in range(0, len(pivots), _FANOUT):
            batch = pivots[i: i + _FANOUT]
            results = await asyncio.gather(*(_mesh_one(p) for p in batch))
            for pivot, rows in zip(batch, results, strict=False):
                for prow in rows:
                    other = prow["collocate"]
                    if other == pivot or other not in G.nodes:
                        continue
                    attrs = _edge_attrs(prow)
                    attrs["weight"] = _row_measure(attrs, req.measure)
                    if not G.has_edge(pivot, other):
                        G.add_edge(pivot, other, **attrs)

    # Safety cap: drop lowest-degree non-center nodes until within budget.
    if G.number_of_nodes() > req.max_nodes:
        ranked = sorted(
            (n for n in G.nodes if n != req.node),
            key=lambda n: (G.degree(n), G.degree(n, weight="weight")),
        )
        for n in ranked[: G.number_of_nodes() - req.max_nodes]:
            G.remove_node(n)

    nodes = [
        _node_payload(n, freq.get(n, 0), n == req.node, G)
        for n in sorted(G.nodes, key=lambda n: (-G.degree(n), n))
    ]
    edges = [
        _edge_payload(u, v, dict(G.edges[u, v]))
        for u, v in sorted(G.edges, key=lambda e: (-G.edges[e].get("weight", 0), e[0], e[1]))
    ]
    density = round(nx.density(G), 6) if G.number_of_nodes() > 1 else 0.0

    return {
        "params": req.model_dump(),
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "density": density,
        },
    }


@router.post("/corpora/{cid}/collocations/network/expand")
async def collocation_network_expand(
    cid: str, req: ExpandRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Fetch one pivot's collocates for progressive graph expansion.

    Returns the pivot's top collocates as nodes (excluding ones the client
    says it already has, to keep payloads small) plus every edge to a node
    already known — new nodes only get spokes; mesh edges to known nodes
    are computed server-side so degrees stay honest.
    """
    # v1.2.14 (P1.2): semaphore + 30s deadline parity with the network
    # endpoint above.
    sem = _get_analysis_semaphore()
    try:
        async with sem:
            return await asyncio.wait_for(
                _collocation_network_expand_impl(cid, req, session),
                timeout=_NETWORK_DEADLINE_S,
            )
    except TimeoutError:
        log.warning("collocation_network_expand_timeout", corpus_id=cid, node=req.node,
                     deadline_s=_NETWORK_DEADLINE_S)
        raise HTTPException(
            504,
            detail=(
                f"Network expansion exceeded the {_NETWORK_DEADLINE_S:.0f}s deadline. "
                "Try a smaller top_n or a more frequent node word."
            ),
        ) from None


async def _collocation_network_expand_impl(
    cid: str, req: ExpandRequest, session: AsyncSession
) -> dict[str, Any]:
    """Inner implementation — wrapped by semaphore + deadline above."""
    try:
        rows = await _pivot_rows(session, cid, req.node, req, limit=req.top_n * 3)
    except Exception as e:
        log.warning("collocation_network_expand_failed", corpus_id=cid, error=str(e))
        raise HTTPException(400, f"Network expansion failed: {e}") from e

    known = set(req.known_nodes) | {req.node}
    G = nx.Graph()
    G.add_node(req.node)
    freq: dict[str, int] = {}

    new_nodes: set[str] = set()
    for row in rows[: req.top_n]:
        collocate = row["collocate"]
        attrs = _edge_attrs(row)
        attrs["weight"] = _row_measure(attrs, req.measure)
        if collocate not in known:
            new_nodes.add(collocate)
        freq.setdefault(collocate, int(row.get("fy", 0) or 0))
        if not G.has_edge(req.node, collocate):
            G.add_edge(req.node, collocate, **attrs)

    # Mesh the new nodes against each other (cheap, bounded by top_n) so a
    # freshly expanded cluster is not a pure star.
    # v1.2.14 (P1.2): parallelise with asyncio.gather under a bounded fan-out.
    if req.depth >= 2 and len(new_nodes) > 1:
        async def _mesh_one(pivot: str) -> list[dict[str, Any]]:
            try:
                pivot_result = await compute_collocations(
                    session,
                    cid,
                    pivot,
                    level=req.level,
                    window=req.window,
                    min_freq=req.min_freq,
                    limit=req.top_n,
                )
                return list(pivot_result.rows)
            except Exception as e:
                log.warning("collocation_network_expand_pivot_failed",
                             pivot=pivot, error=str(e))
                return []

        pivots = list(new_nodes)[: req.top_n]
        for i in range(0, len(pivots), _FANOUT):
            batch = pivots[i: i + _FANOUT]
            results = await asyncio.gather(*(_mesh_one(p) for p in batch))
            for pivot, rows in zip(batch, results, strict=False):
                for prow in rows:
                    other = prow["collocate"]
                    if other == pivot or other not in G.nodes:
                        continue
                    attrs = _edge_attrs(prow)
                    attrs["weight"] = _row_measure(attrs, req.measure)
                    if not G.has_edge(pivot, other):
                        G.add_edge(pivot, other, **attrs)

    nodes = [
        _node_payload(n, freq.get(n, 0), n == req.node, G)
        for n in sorted(G.nodes, key=lambda n: (-G.degree(n), n))
    ]
    edges = [
        _edge_payload(u, v, dict(G.edges[u, v]))
        for u, v in sorted(G.edges, key=lambda e: (-G.edges[e].get("weight", 0), e[0], e[1]))
    ]

    return {
        "params": req.model_dump(),
        "nodes": nodes,
        "edges": edges,
        "new_nodes": sorted(new_nodes),
        "stats": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "density": round(nx.density(G), 6) if G.number_of_nodes() > 1 else 0.0,
        },
    }
