"""Matplotlib figures, rendered server-side to PNG or SVG.

Uses the object-oriented API (``Figure`` + Agg canvas) rather than ``pyplot``,
so concurrent requests never share global figure state.

Style rules (shared with the web UI): one categorical palette in fixed slot
order; scatter and network views colour at most three highlighted topics and
grey the rest; many-topic timelines are small multiples in a single hue;
hairline solid grids; text in ink colours, never in series colours.
"""

from __future__ import annotations

import io
import math
import textwrap
import threading
from collections.abc import Sequence

import matplotlib

matplotlib.use("Agg")

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "context": "#d6d5ce",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#ffffff", "secondary": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "context": "#3d3d3a",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    },
}
FONT = {"family": "DejaVu Sans", "size": 9}
_render_lock = threading.Lock()


def _theme(name: str) -> dict:
    return THEMES.get(name, THEMES["light"])


def _figure(width: float, height: float, theme: dict) -> Figure:
    fig = Figure(figsize=(width, height), dpi=110, facecolor=theme["surface"])
    FigureCanvasAgg(fig)
    return fig


def _style_axes(ax, theme: dict, grid_axis: str | None = "both") -> None:
    ax.set_facecolor(theme["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["axis"])
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=theme["muted"], labelsize=8, length=0)
    if grid_axis:
        ax.grid(True, axis=grid_axis, color=theme["grid"], linewidth=0.7, linestyle="-")
        ax.set_axisbelow(True)


def _title(fig: Figure, title: str, subtitle: str | None, theme: dict) -> None:
    fig.text(0.012, 0.985, title, ha="left", va="top", fontsize=12, fontweight="bold", color=theme["ink"], **_font())
    if subtitle:
        fig.text(0.012, 0.935, subtitle, ha="left", va="top", fontsize=8.5, color=theme["secondary"], **_font())


def _font() -> dict:
    return {"family": FONT["family"]}


def _encode(fig: Figure, fmt: str) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format=fmt, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.18)
    return buffer.getvalue()


def _shorten(text: str, width: int) -> str:
    return textwrap.shorten(text or "", width=width, placeholder="…")


def render(kind: str, fmt: str = "png", theme: str = "light", **data) -> bytes:
    """Entry point used by the API: ``render("topic_map", points=..., topics=...)``."""
    builder = FIGURES[kind]
    with _render_lock:
        fig = builder(theme=_theme(theme), **data)
        return _encode(fig, "svg" if fmt == "svg" else "png")


# --------------------------------------------------------------------------- topic map


def topic_map(theme: dict, points: Sequence[dict], topics: Sequence[dict],
              highlight: Sequence[int] = (), dims: int = 2, elev: float = 22, azim: float = -58) -> Figure:
    """Documents in concept space (PCA of LSA vectors); up to 3 topics highlighted."""
    fig = _figure(8.6, 6.2, theme)
    labels = {t["id"]: t["label"] for t in topics}
    highlight = [h for h in highlight if h in labels][:3]
    xyz = np.array([[p["x"], p["y"], p.get("z", 0.0)] for p in points]) if points else np.zeros((0, 3))
    clusters = np.array([p.get("cluster", -1) for p in points])
    context = ~np.isin(clusters, highlight)

    if dims == 3:
        ax = fig.add_axes([0.0, 0.0, 0.8, 0.88], projection="3d")
        ax.set_facecolor(theme["surface"])
        for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
            pane.set_pane_color((0, 0, 0, 0))
            pane._axinfo["grid"]["color"] = theme["grid"]
            pane._axinfo["grid"]["linewidth"] = 0.6
            pane.line.set_color(theme["axis"])
        ax.tick_params(colors=theme["muted"], labelsize=7)
        ax.scatter(*xyz[context].T, s=10, c=theme["context"], depthshade=False, linewidths=0)
        for slot, cluster in enumerate(highlight):
            mask = clusters == cluster
            ax.scatter(*xyz[mask].T, s=26, c=theme["series"][slot], depthshade=False,
                       edgecolors=theme["surface"], linewidths=0.8, label=labels[cluster])
        ax.view_init(elev=elev, azim=azim)
        ax.set_xlabel("PC 1", color=theme["muted"], fontsize=8)
        ax.set_ylabel("PC 2", color=theme["muted"], fontsize=8)
        ax.set_zlabel("PC 3", color=theme["muted"], fontsize=8)
    else:
        ax = fig.add_axes([0.07, 0.08, 0.68, 0.8])
        _style_axes(ax, theme)
        ax.scatter(xyz[context, 0], xyz[context, 1], s=12, c=theme["context"], linewidths=0)
        for slot, cluster in enumerate(highlight):
            mask = clusters == cluster
            ax.scatter(xyz[mask, 0], xyz[mask, 1], s=30, c=theme["series"][slot],
                       edgecolors=theme["surface"], linewidths=1.0, label=labels[cluster])
            if mask.any():  # direct label at the topic's centre
                cx, cy = np.median(xyz[mask, 0]), np.median(xyz[mask, 1])
                ax.annotate(_shorten(labels[cluster], 28), (cx, cy), xytext=(0, 14), textcoords="offset points",
                            ha="center", fontsize=8.5, fontweight="bold", color=theme["ink"],
                            bbox={"boxstyle": "round,pad=0.25", "fc": theme["surface"], "ec": "none", "alpha": 0.85})
        ax.set_xlabel("Concept axis 1 (PCA of LSA vectors)", color=theme["muted"], fontsize=8)
        ax.set_ylabel("Concept axis 2", color=theme["muted"], fontsize=8)

    if highlight:
        legend = ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False, fontsize=8.5,
                           labelcolor=theme["ink"], handletextpad=0.4, borderaxespad=0)
        legend.set_title("Highlighted topics", prop={"size": 8.5, "weight": "bold"})
        legend.get_title().set_color(theme["secondary"])
    fig.text(0.79, 0.12, f"{len(points):,} documents\n{int(context.sum()):,} in other topics (grey)",
             color=theme["muted"], fontsize=8, va="bottom")
    _title(fig, "Topic map", f"{'3-D' if dims == 3 else '2-D'} projection of the LSA concept space", theme)
    return fig


def topic_facets(theme: dict, points: Sequence[dict], topics: Sequence[dict], limit: int = 12) -> Figure:
    """Small multiples: each panel highlights one topic against all documents."""
    shown = sorted(topics, key=lambda t: -t.get("size", 0))[:limit]
    cols = 4
    rows = max(1, math.ceil(len(shown) / cols))
    fig = _figure(10.5, 2.35 * rows + 0.7, theme)
    xy = np.array([[p["x"], p["y"]] for p in points]) if points else np.zeros((0, 2))
    clusters = np.array([p.get("cluster", -1) for p in points])
    top = 1 - 0.7 / (2.35 * rows + 0.7)
    grid = fig.add_gridspec(rows, cols, left=0.02, right=0.98, bottom=0.02, top=top - 0.02, hspace=0.32, wspace=0.08)
    for i, topic in enumerate(shown):
        ax = fig.add_subplot(grid[i // cols, i % cols])
        ax.set_facecolor(theme["surface"])
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(theme["grid"])
        mask = clusters == topic["id"]
        ax.scatter(xy[~mask, 0], xy[~mask, 1], s=4, c=theme["context"], linewidths=0)
        ax.scatter(xy[mask, 0], xy[mask, 1], s=9, c=theme["series"][0], linewidths=0)
        ax.set_title(f"{_shorten(topic['label'], 30)}  ·  {topic.get('size', int(mask.sum()))}",
                     fontsize=8, color=theme["ink"], loc="left", pad=3)
    _title(fig, "Where each topic lives", "One panel per topic, all documents in grey for context", theme)
    return fig


# --------------------------------------------------------------------------- time


def topic_timeline(theme: dict, timeline: dict, topics: Sequence[dict], limit: int = 12) -> Figure:
    """Small multiples of documents per year for each topic (shared y-axis)."""
    years = np.array(timeline.get("years", []))
    counts = np.array(timeline.get("counts", []))
    shown = sorted(topics, key=lambda t: -t.get("size", 0))[:limit]
    cols = 4
    rows = max(1, math.ceil(len(shown) / cols))
    fig = _figure(10.5, 1.9 * rows + 0.75, theme)
    top = 1 - 0.75 / (1.9 * rows + 0.75)
    grid = fig.add_gridspec(rows, cols, left=0.05, right=0.99, bottom=0.06, top=top - 0.02, hspace=0.55, wspace=0.12)
    ymax = max(1, int(counts.max())) if counts.size else 1
    color = theme["series"][0]
    for i, topic in enumerate(shown):
        ax = fig.add_subplot(grid[i // cols, i % cols])
        _style_axes(ax, theme, grid_axis="y")
        series = counts[topic["id"]] if topic["id"] < len(counts) else np.zeros_like(years)
        ax.fill_between(years, series, color=color, alpha=0.12, linewidth=0)
        ax.plot(years, series, color=color, linewidth=1.6, solid_capstyle="round", solid_joinstyle="round")
        if len(years):
            peak = int(np.argmax(series))
            ax.plot([years[peak]], [series[peak]], "o", ms=4.5, color=color, mec=theme["surface"], mew=1.2)
            ax.annotate(f"{int(series[peak])} in {years[peak]}", (years[peak], series[peak]), xytext=(0, 5),
                        textcoords="offset points", ha="center", fontsize=7, color=theme["secondary"])
        ax.set_ylim(0, ymax * 1.25)
        ax.set_title(_shorten(topic["label"], 32), fontsize=8, color=theme["ink"], loc="left", pad=3)
        if i % cols:
            ax.set_yticklabels([])
    _title(fig, "Topics over time", "Documents per year in each topic (shared scale)", theme)
    return fig


def bursts(theme: dict, bursts: Sequence[dict], limit: int = 18) -> Figure:
    """Kleinberg burst intervals as horizontal bars on a year axis."""
    shown = list(bursts)[:limit]
    fig = _figure(9.0, 0.36 * max(4, len(shown)) + 1.1, theme)
    ax = fig.add_axes([0.26, 0.1, 0.68, 0.76])
    _style_axes(ax, theme, grid_axis="x")
    color = theme["series"][0]
    for row, burst in enumerate(shown):
        ax.barh(row, burst["end"] - burst["start"] + 1, left=burst["start"] - 0.5, height=0.55,
                color=color, linewidth=0)
        ax.text(burst["end"] + 0.9, row, f"{burst['weight']:.0f}", va="center", fontsize=7.5, color=theme["muted"])
    ax.set_yticks(range(len(shown)))
    ax.set_yticklabels([_shorten(b["label"], 34) for b in shown], fontsize=8, color=theme["ink"])
    ax.invert_yaxis()
    if shown:
        lo = min(b["start"] for b in shown)
        hi = max(b["end"] for b in shown)
        ax.set_xlim(lo - 2, hi + 4)
    _title(fig, "Bursts of activity", "Kleinberg two-state bursts; number = burst strength", theme)
    return fig


# --------------------------------------------------------------------------- graphs


def citation_graph(theme: dict, network: dict, label_top: int = 8, seed: int = 7) -> Figure:
    """Most influential papers; node area follows PageRank."""
    fig = _figure(9.2, 7.2, theme)
    ax = fig.add_axes([0.01, 0.01, 0.98, 0.88])
    ax.set_facecolor(theme["surface"])
    ax.axis("off")
    graph = nx.Graph()
    graph.add_nodes_from(n["id"] for n in network.get("nodes", []))
    graph.add_edges_from((link["source"], link["target"]) for link in network.get("links", []))
    if graph.number_of_edges() == 0:
        ax.text(0.5, 0.5, "No citation links yet", ha="center", color=theme["muted"])
        return fig
    # Small disconnected islands would squash the main picture; draw the largest component.
    core = max(nx.connected_components(graph), key=len)
    graph = graph.subgraph(core)
    nodes = [n for n in network["nodes"] if n["id"] in core]
    pos = nx.spring_layout(graph, seed=seed, k=2.2 / math.sqrt(len(nodes)), iterations=200)
    ranks = np.array([n.get("pagerank", 0.0) for n in nodes])
    sizes = 14 + 420 * (ranks / ranks.max()) if ranks.max() > 0 else np.full(len(nodes), 30)
    nx.draw_networkx_edges(graph, pos, ax=ax, edge_color=theme["axis"], width=0.45, alpha=0.8)
    nx.draw_networkx_nodes(graph, pos, nodelist=[n["id"] for n in nodes], node_size=sizes, ax=ax,
                           node_color=theme["series"][0], edgecolors=theme["surface"], linewidths=0.9)
    for node in sorted(nodes, key=lambda n: -n.get("pagerank", 0))[:label_top]:
        x, y = pos[node["id"]]
        ax.annotate(_shorten(node["label"], 34), (x, y), xytext=(0, 10), textcoords="offset points",
                    ha="center", fontsize=7.5, color=theme["ink"],
                    bbox={"boxstyle": "round,pad=0.2", "fc": theme["surface"], "ec": "none", "alpha": 0.85})
    hidden = len(network["nodes"]) - len(nodes)
    if hidden:
        fig.text(0.012, 0.02, f"{hidden} papers outside the largest connected component are not drawn",
                 color=theme["muted"], fontsize=7.5)
    _title(fig, "Citation network", f"Top {len(network['nodes'])} papers by PageRank · node area = PageRank", theme)
    return fig


def pagerank_bars(theme: dict, papers: Sequence[dict]) -> Figure:
    fig = _figure(9.0, 0.38 * max(4, len(papers)) + 1.0, theme)
    ax = fig.add_axes([0.42, 0.08, 0.5, 0.78])
    _style_axes(ax, theme, grid_axis="x")
    values = [p.get("pagerank", 0.0) * 1000 for p in papers]
    ax.barh(range(len(papers)), values, height=0.55, color=theme["series"][0], linewidth=0)
    for row, value in enumerate(values):
        ax.text(value, row, f"  {value:.2f}", va="center", fontsize=7.5, color=theme["secondary"])
    ax.set_yticks(range(len(papers)))
    ax.set_yticklabels([f"{_shorten(p['label'], 52)} ({p.get('year') or '?'})" for p in papers],
                       fontsize=8, color=theme["ink"])
    ax.invert_yaxis()
    ax.set_xlabel("PageRank × 1000", color=theme["muted"], fontsize=8)
    _title(fig, "Most influential papers", "PageRank on the in-corpus citation graph", theme)
    return fig


def degree_distribution(theme: dict, distribution: dict) -> Figure:
    fig = _figure(7.0, 4.6, theme)
    ax = fig.add_axes([0.11, 0.12, 0.85, 0.72])
    _style_axes(ax, theme)
    pairs = sorted((int(k), int(v)) for k, v in distribution.items() if int(k) > 0)
    if pairs:
        degrees, counts = zip(*pairs)
        ax.scatter(degrees, counts, s=34, c=theme["series"][0], edgecolors=theme["surface"], linewidths=1.0)
        ax.set_xscale("log")
        ax.set_yscale("log")
    ax.set_xlabel("Times cited inside the corpus (in-degree)", color=theme["muted"], fontsize=8)
    ax.set_ylabel("Number of papers", color=theme["muted"], fontsize=8)
    _title(fig, "Citation degree distribution", "Log-log; a straight-ish line suggests a heavy tail", theme)
    return fig


def evolution(theme: dict, evolution: dict) -> Figure:
    """Temporal concept graph: eras left to right, topics as nodes, continuity as links."""
    eras = evolution.get("eras", [])
    nodes = evolution.get("nodes", [])
    fig = _figure(11.0, 6.8, theme)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.8])
    ax.set_facecolor(theme["surface"])
    ax.axis("off")
    if not nodes:
        ax.text(0.5, 0.5, "Not enough dated documents yet", ha="center", color=theme["muted"])
        return fig
    by_era: dict[int, list[dict]] = {}
    for node in nodes:
        by_era.setdefault(node["era"], []).append(node)
    pos = {}
    for era, members in by_era.items():
        members.sort(key=lambda n: -n["size"])
        for i, node in enumerate(members):
            pos[node["id"]] = (era, -(i - (len(members) - 1) / 2))
    max_size = max(n["size"] for n in nodes)
    for link in evolution.get("links", []):
        (x0, y0), (x1, y1) = pos[link["source"]], pos[link["target"]]
        xs = np.linspace(x0, x1, 30)
        t = (xs - x0) / (x1 - x0)
        ys = y0 + (y1 - y0) * (3 * t**2 - 2 * t**3)  # smooth S-curve
        ax.plot(xs, ys, color=theme["axis"], linewidth=0.6 + 3.0 * max(0.0, link["weight"] - 0.5),
                alpha=0.45 if link.get("weak") else 0.9, solid_capstyle="round", zorder=1)
    events = {}
    for event in evolution.get("events", []):
        if event["type"] in ("split", "merge"):
            events.setdefault(event["node"], []).append(event["type"])
    for node in nodes:
        x, y = pos[node["id"]]
        ax.scatter([x], [y], s=60 + 640 * node["size"] / max_size, c=theme["series"][0],
                   edgecolors=theme["surface"], linewidths=1.5, zorder=2)
        tag = f"  [{' + '.join(events[node['id']])}]" if node["id"] in events else ""
        ax.text(x, y - 0.3, _shorten(node["label"], 26) + tag, ha="center", va="top", fontsize=7,
                color=theme["ink"] if tag else theme["secondary"], zorder=3)
    top = max(p[1] for p in pos.values())
    for era in eras:
        ax.text(era["index"], top + 0.75, era["label"], ha="center",
                fontsize=8.5, fontweight="bold", color=theme["secondary"])
    ax.set_xlim(-0.6, max(len(eras) - 0.4, 0.6))
    ax.set_ylim(min(p[1] for p in pos.values()) - 0.8, top + 1.1)
    _title(fig, "Temporal concept graph",
           "Topics per era; links join similar topics in consecutive eras, tags mark splits and merges", theme)
    return fig


FIGURES = {
    "topic_map": topic_map,
    "topic_facets": topic_facets,
    "topic_timeline": topic_timeline,
    "bursts": bursts,
    "citation_graph": citation_graph,
    "pagerank": pagerank_bars,
    "degree_distribution": degree_distribution,
    "evolution": evolution,
}
