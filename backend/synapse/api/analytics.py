"""Corpus analytics: overview, topics, timelines, bursts, evolution, graphs and figures."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from ..viz import plots
from .deps import NodeDep

router = APIRouter(tags=["analytics"])

_figure_cache: OrderedDict[tuple, bytes] = OrderedDict()
_cache_lock = threading.Lock()
FIGURE_CACHE_SIZE = 64


def _analytics(node) -> dict:
    analytics = node.engine.analytics
    if not analytics:
        raise HTTPException(404, "Analytics are not ready yet; ingest documents or rebuild the model")
    return analytics


def _points(node, limit: int) -> list[dict]:
    nodes = node.cluster.alive_nodes()
    replies = node.cluster.broadcast("POINTS", {"limit": max(50, limit // max(1, len(nodes)))}, timeout=15)
    return [p | {"node": n} for n, r in replies.items() if r.ok for p in r.payload["points"]]


@router.get("/analytics/overview")
def overview(node: NodeDep):
    """Everything the landing page shows: stats, trends, popular searches, new arrivals."""
    analytics = node.engine.analytics or {}
    peers = [p for p in node.cluster.peers() if p.alive]
    documents = len(node.engine.meta) + sum(p.info.get("documents", 0) for p in peers)
    topics = analytics.get("topics", [])
    trending = sorted((t for t in topics if t["size"] >= 8), key=lambda t: -t["growth"])[:6]
    timeline_years = analytics.get("timeline", {}).get("years", [])
    latest = timeline_years[-1] if timeline_years else None
    bursts = analytics.get("bursts", {})
    active = [b for b in bursts.get("terms", []) + bursts.get("topics", []) if latest and b["end"] >= latest - 3]
    active.sort(key=lambda b: -b["weight"])
    return {
        "node": node.settings.node_id,
        "documents": documents,
        "nodes": {"alive": len(peers) + 1, "known": len(node.cluster.peers()) + 1},
        "graph": analytics.get("graph_stats", {}),
        "model": node.engine.model.info() if node.engine.model else None,
        "trending": [{k: t[k] for k in ("id", "label", "size", "growth", "recent", "terms")} for t in trending],
        "bursts": active[:8],
        "popular": node.popular_queries(8),
        "recent_searches": node.app.recent_queries(8),
        "recent_documents": node.recent_documents(6),
        "top_papers": analytics.get("top_papers", [])[:6],
        "year_range": [timeline_years[0], timeline_years[-1]] if timeline_years else None,
    }


@router.get("/analytics/topics")
def topics(node: NodeDep):
    analytics = _analytics(node)
    return {"topics": analytics["topics"], "version": analytics["version"]}


@router.get("/analytics/timeline")
def timeline(node: NodeDep):
    analytics = _analytics(node)
    return {"timeline": analytics["timeline"],
            "topics": [{"id": t["id"], "label": t["label"], "size": t["size"]} for t in analytics["topics"]]}


@router.get("/analytics/bursts")
def bursts(node: NodeDep):
    return _analytics(node)["bursts"]


@router.get("/analytics/evolution")
def evolution(node: NodeDep):
    return _analytics(node)["evolution"]


@router.get("/analytics/points")
def points(node: NodeDep, limit: Annotated[int, Query(ge=50, le=10_000)] = 3000):
    """Every document's position in concept space (PCA of LSA vectors), from all shards."""
    analytics = _analytics(node)
    return {"points": _points(node, limit),
            "topics": [{"id": t["id"], "label": t["label"], "size": t["size"]} for t in analytics["topics"]]}


@router.get("/analytics/influence")
def influence(node: NodeDep):
    analytics = _analytics(node)
    return {"papers": analytics["top_papers"], "authors": analytics["top_authors"],
            "stats": analytics["graph_stats"]}


# --------------------------------------------------------------------------- graphs


@router.get("/graph/citations")
def citation_network(node: NodeDep, limit: Annotated[int, Query(ge=10, le=1500)] = 250,
                     topic: int | None = None, year_from: int | None = None, year_to: int | None = None):
    graph = node.engine.graph
    if graph is None:
        raise HTTPException(404, "The knowledge graph has not been built yet")
    return graph.citation_network(limit, topic, year_from, year_to)


@router.get("/graph/authors")
def collaboration_network(node: NodeDep, limit: Annotated[int, Query(ge=10, le=600)] = 150):
    graph = node.engine.graph
    if graph is None:
        raise HTTPException(404, "The knowledge graph has not been built yet")
    return graph.collaboration_network(limit)


@router.get("/graph/path")
def path(node: NodeDep, source: str, target: str):
    """Shortest chain of citations (in either direction) linking two papers."""
    graph = node.engine.graph
    if graph is None:
        raise HTTPException(404, "The knowledge graph has not been built yet")
    route = graph.shortest_path(source, target)
    if route is None:
        return {"found": False, "path": []}
    steps = []
    for a, b in zip(route, route[1:]):
        steps.append("cites" if graph.citations.has_edge(a, b) else "cited by")
    return {"found": True, "path": [graph._node(d, "path") for d in route], "steps": steps}


@router.get("/graph/stats")
def graph_stats(node: NodeDep):
    return _analytics(node)["graph_stats"]


# --------------------------------------------------------------------------- figures

FIGURES = ("topic_map", "topic_facets", "topic_timeline", "bursts", "citation_graph", "pagerank",
           "degree_distribution", "evolution")


@router.get("/viz/{name}.{fmt}")
async def figure(
    name: Literal[FIGURES],  # type: ignore[valid-type]
    fmt: Literal["png", "svg"],
    node: NodeDep,
    theme: Literal["light", "dark"] = "light",
    highlight: str | None = None,
    dims: Annotated[int, Query(ge=2, le=3)] = 2,
    elev: Annotated[float, Query(ge=-90, le=90)] = 22,
    azim: Annotated[float, Query(ge=-180, le=180)] = -58,
    limit: Annotated[int, Query(ge=20, le=400)] = 150,
):
    """Server-side Matplotlib renderings of the analytics (PNG or SVG)."""
    analytics = _analytics(node)
    picked = tuple(int(x) for x in highlight.split(",") if x.strip().lstrip("-").isdigit())[:3] if highlight else ()
    key = (name, fmt, theme, picked, dims, round(elev), round(azim), limit, analytics["version"])
    with _cache_lock:
        if key in _figure_cache:
            _figure_cache.move_to_end(key)
            return Response(_figure_cache[key], media_type="image/svg+xml" if fmt == "svg" else "image/png",
                            headers={"Cache-Control": "public, max-age=300"})

    def build() -> bytes:
        topics_list = analytics["topics"]
        if name in ("topic_map", "topic_facets"):
            points = _points(node, 4000)
            default = [t["id"] for t in sorted(topics_list, key=lambda t: -t["size"])[:3]]
            data = {"points": points, "topics": topics_list}
            if name == "topic_map":
                data.update(highlight=list(picked) or default, dims=dims, elev=elev, azim=azim)
        elif name == "topic_timeline":
            data = {"timeline": analytics["timeline"], "topics": topics_list}
        elif name == "bursts":
            merged = analytics["bursts"]["topics"] + analytics["bursts"]["terms"]
            data = {"bursts": sorted(merged, key=lambda b: -b["weight"])[:18]}
        elif name == "citation_graph":
            data = {"network": node.engine.graph.citation_network(limit)}
        elif name == "pagerank":
            data = {"papers": node.engine.graph.top_papers(15)}
        elif name == "degree_distribution":
            data = {"distribution": analytics["degree_distribution"]}
        else:
            data = {"evolution": analytics["evolution"]}
        return plots.render(name, fmt=fmt, theme=theme, **data)

    content = await run_in_threadpool(build)
    with _cache_lock:
        _figure_cache[key] = content
        while len(_figure_cache) > FIGURE_CACHE_SIZE:
            _figure_cache.popitem(last=False)
    return Response(content, media_type="image/svg+xml" if fmt == "svg" else "image/png",
                    headers={"Cache-Control": "public, max-age=300"})
