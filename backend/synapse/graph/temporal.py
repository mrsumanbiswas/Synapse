"""Temporal concept graphs: how research topics grow, burst, merge and split.

* **Timeline**: documents per topic per year.
* **Bursts**: Kleinberg's two-state automaton ("Bursty and hierarchical
  structure in streams", 2002). A topic or term enters the "burst" state when
  its share of a year's documents jumps well above its base rate, and leaving
  that state is free while entering it costs ``gamma * ln(n)``. The cheapest
  state sequence (Viterbi) marks the bursts.
* **Evolution graph**: the corpus is cut into eras, each era is clustered on its
  own, and topics of consecutive eras are linked (networkx DiGraph) when their
  centroids are similar. Two strong successors mean a topic *split*; two strong
  predecessors mean lines of work *merged*.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import networkx as nx
import numpy as np

from ..vector.clustering import kmeans


def kleinberg_bursts(relevant: Sequence[float], totals: Sequence[float], s: float = 2.0,
                     gamma: float = 1.0) -> list[tuple[int, int, float]]:
    """Burst intervals as (start index, end index, weight) for a batched series."""
    r = np.asarray(relevant, dtype=float)
    d = np.asarray(totals, dtype=float)
    n = len(r)
    if n < 2 or r.sum() == 0 or d.sum() == 0:
        return []
    p0 = r.sum() / d.sum()
    p1 = min(p0 * s, 0.9999)
    if p1 <= p0:
        return []
    valid = d > 0

    def cost(p: float) -> np.ndarray:
        c = -(r * math.log(p) + (d - r) * math.log(1 - p))
        c[~valid] = 0.0
        return c

    c0, c1 = cost(p0), cost(p1)
    rise = gamma * math.log(n)
    best = np.zeros((n, 2))
    back = np.zeros((n, 2), dtype=int)
    best[0] = (c0[0], c1[0] + rise)
    for t in range(1, n):
        from_low, from_high = best[t - 1]
        # Into the base state: dropping out of a burst is free.
        if from_low <= from_high:
            best[t, 0], back[t, 0] = from_low + c0[t], 0
        else:
            best[t, 0], back[t, 0] = from_high + c0[t], 1
        # Into the burst state: entering costs `rise`, staying is free.
        if from_high <= from_low + rise:
            best[t, 1], back[t, 1] = from_high + c1[t], 1
        else:
            best[t, 1], back[t, 1] = from_low + rise + c1[t], 0

    states = np.zeros(n, dtype=int)
    states[-1] = int(best[-1].argmin())
    for t in range(n - 1, 0, -1):
        states[t - 1] = back[t, states[t]]

    bursts, t = [], 0
    while t < n:
        if states[t] == 1:
            start = t
            while t + 1 < n and states[t + 1] == 1:
                t += 1
            bursts.append((start, t, float((c0[start : t + 1] - c1[start : t + 1]).sum())))
        t += 1
    return bursts


def year_axis(years: Sequence[int | None], coverage: float = 0.02) -> list[int]:
    """Continuous year range, trimming the sparse early tail (first ``coverage`` of docs)."""
    known = sorted(y for y in years if y)
    if not known:
        return []
    start = known[min(len(known) - 1, int(len(known) * coverage))]
    return list(range(start, known[-1] + 1))


def timeline(years: Sequence[int | None], clusters: Sequence[int], n_clusters: int,
             axis: list[int]) -> dict:
    index = {year: i for i, year in enumerate(axis)}
    counts = np.zeros((n_clusters, len(axis)), dtype=int)
    for year, cluster in zip(years, clusters):
        if year in index and 0 <= cluster < n_clusters:
            counts[cluster, index[year]] += 1
    return {"years": axis, "counts": counts.tolist(), "totals": counts.sum(axis=0).tolist()}


def find_bursts(series: dict[str, Sequence[float]], totals: Sequence[float], axis: list[int],
                kind: str, min_weight: float = 2.0) -> list[dict]:
    found = []
    for label, counts in series.items():
        for start, end, weight in kleinberg_bursts(counts, totals):
            if weight >= min_weight:
                found.append({
                    "label": label, "kind": kind, "start": axis[start], "end": axis[end],
                    "weight": round(weight, 2), "documents": int(sum(counts[start : end + 1])),
                })
    return sorted(found, key=lambda b: -b["weight"])


def eras(years: Sequence[int | None], n_eras: int = 6, min_docs: int = 30) -> list[tuple[int, int]]:
    """Year ranges holding roughly equal numbers of documents."""
    known = np.array(sorted(y for y in years if y))
    if len(known) < min_docs * 2:
        return [(int(known[0]), int(known[-1]))] if len(known) else []
    cuts = sorted({int(np.quantile(known, q)) for q in np.linspace(0, 1, n_eras + 1)[1:-1]})
    bounds, low = [], int(known[0])
    for cut in cuts + [int(known[-1])]:
        if cut < low:
            continue
        bounds.append((low, cut))
        low = cut + 1
    merged: list[tuple[int, int]] = []
    for lo, hi in bounds:
        size = int(((known >= lo) & (known <= hi)).sum())
        if merged and (size < min_docs or merged[-1][2] < min_docs):
            plo, _, psize = merged.pop()
            merged.append((plo, hi, psize + size))
        else:
            merged.append((lo, hi, size))
    if len(merged) > 1 and merged[-1][2] < min_docs:
        lo, hi, size = merged.pop()
        plo, _, psize = merged.pop()
        merged.append((plo, hi, psize + size))
    return [(lo, hi) for lo, hi, _ in merged]


def evolution_graph(years: Sequence[int | None], vectors: np.ndarray,
                    label: Callable[[np.ndarray, np.ndarray], str],
                    n_eras: int = 6, link_threshold: float = 0.68, tolerance: float = 0.05,
                    seed: int = 42) -> dict:
    """Cluster each era separately and link similar topics across consecutive eras."""
    years_arr = np.array([y or 0 for y in years])
    graph = nx.DiGraph()
    periods = eras(list(years), n_eras=n_eras)
    layers: list[list[tuple[str, np.ndarray]]] = []

    for era_index, (lo, hi) in enumerate(periods):
        members = np.where((years_arr >= lo) & (years_arr <= hi))[0]
        if len(members) < 4:
            layers.append([])
            continue
        k = int(min(7, max(2, round(math.sqrt(len(members) / 6)))))
        centroids, labels = kmeans(vectors[members], k, seed=seed)
        layer = []
        for c, centroid in enumerate(centroids):
            idx = members[labels == c]
            if len(idx) < 3:
                continue
            node_id = f"e{era_index}c{c}"
            graph.add_node(node_id, era=era_index, period=f"{lo}–{hi}", start=lo, end=hi,
                           size=int(len(idx)), label=label(centroid, idx))
            layer.append((node_id, centroid))
        layers.append(layer)

    for earlier, later in zip(layers, layers[1:]):
        if not earlier or not later:
            continue
        sims = np.array([[float(ca @ cb) for _, cb in later] for _, ca in earlier])
        best_out, best_in = sims.max(axis=1), sims.max(axis=0)
        for i, (a, _) in enumerate(earlier):
            for j, (b, _) in enumerate(later):
                sim = sims[i, j]
                # A link must be strong in absolute terms and close to the best option on
                # at least one side; otherwise every topic would "split" into everything.
                if sim >= link_threshold and (sim >= best_out[i] - tolerance or sim >= best_in[j] - tolerance):
                    graph.add_edge(a, b, weight=round(float(sim), 3))
            if graph.out_degree(a) == 0 and best_out[i] >= link_threshold * 0.75:
                j = int(sims[i].argmax())  # keep each line of work's best continuation
                graph.add_edge(a, later[j][0], weight=round(float(best_out[i]), 3), weak=True)

    last_era = len(periods) - 1
    events = []
    for node, data in graph.nodes(data=True):
        strong_out = [v for v in graph.successors(node) if not graph.edges[node, v].get("weak")]
        strong_in = [u for u in graph.predecessors(node) if not graph.edges[u, node].get("weak")]
        if len(strong_out) >= 2:
            events.append({"type": "split", "node": node, "era": data["period"], "label": data["label"],
                           "into": [graph.nodes[v]["label"] for v in strong_out]})
        if len(strong_in) >= 2:
            events.append({"type": "merge", "node": node, "era": data["period"], "label": data["label"],
                           "from": [graph.nodes[u]["label"] for u in strong_in]})
        if data["era"] > 0 and graph.in_degree(node) == 0:
            events.append({"type": "emerge", "node": node, "era": data["period"], "label": data["label"]})
        if data["era"] < last_era and graph.out_degree(node) == 0:
            events.append({"type": "fade", "node": node, "era": data["period"], "label": data["label"]})

    return {
        "eras": [{"index": i, "start": lo, "end": hi, "label": f"{lo}–{hi}"} for i, (lo, hi) in enumerate(periods)],
        "nodes": [{"id": n, **d} for n, d in graph.nodes(data=True)],
        "links": [{"source": u, "target": v, "weight": d["weight"], "weak": bool(d.get("weak"))}
                  for u, v, d in graph.edges(data=True)],
        "events": events,
    }
