"""The knowledge graph: who cites whom, and who writes with whom (networkx).

* Citation graph: papers are nodes, a directed edge ``A -> B`` means A cites B.
  PageRank (Brin & Page, 1998) and HITS hubs/authorities (Kleinberg, 1999)
  measure influence; Louvain (Blondel et al., 2008) finds research communities.
* Collaboration graph: authors are nodes, co-authorship edges carry weights.

The cluster builds this graph once per model rebuild and replicates the
payload to every node, so any peer can answer graph queries locally.
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from collections.abc import Iterable

import networkx as nx
import numpy as np

from ..text.tokenizer import fold

log = logging.getLogger(__name__)
MAX_AUTHORS_PER_PAPER = 25  # mega-collaborations would otherwise add huge cliques


def author_key(name: str) -> str:
    return " ".join(fold(name).replace(".", " ").split())


def h_index(citation_counts: Iterable[int]) -> int:
    counts = sorted(citation_counts, reverse=True)
    return sum(1 for i, c in enumerate(counts, 1) if c >= i)


class KnowledgeGraph:
    def __init__(self) -> None:
        self.citations = nx.DiGraph()
        self.coauthors = nx.Graph()
        self.docs: dict[str, dict] = {}
        self.metrics: dict[str, dict] = {}
        self.author_metrics: dict[str, dict] = {}
        self.author_docs: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ building

    @classmethod
    def build(cls, docs: list[dict], edges: list[tuple[str, str]]) -> "KnowledgeGraph":
        """``docs``: light metadata dicts with id/title/year/cluster/authors/node."""
        graph = cls()
        for doc in docs:
            graph.docs[doc["id"]] = doc
            graph.citations.add_node(doc["id"])
        graph.citations.add_edges_from((a, b) for a, b in edges if a != b and a in graph.docs and b in graph.docs)
        graph._compute_paper_metrics()
        graph._build_coauthors()
        return graph

    def _compute_paper_metrics(self) -> None:
        g = self.citations
        if g.number_of_nodes() == 0:
            return
        pagerank = nx.pagerank(g, alpha=0.85)
        try:
            with np.errstate(divide="ignore", invalid="ignore"):
                hubs, authorities = nx.hits(g, max_iter=500)
        except nx.PowerIterationFailedConvergence:
            hubs, authorities = {}, {}
        # HITS divides by the largest score, which is 0 on graphs without edges: keep JSON finite.
        hubs = {n: float(v) if math.isfinite(v) else 0.0 for n, v in hubs.items()}
        authorities = {n: float(v) if math.isfinite(v) else 0.0 for n, v in authorities.items()}

        communities: dict[str, int] = {}
        undirected = g.to_undirected()
        if undirected.number_of_edges():
            groups = nx.community.louvain_communities(undirected, seed=42)
            groups = sorted((c for c in groups if len(c) >= 3), key=len, reverse=True)
            for index, members in enumerate(groups):
                for node in members:
                    communities[node] = index

        ranks = np.array([pagerank[n] for n in g])
        order = ranks.argsort().argsort()  # rank position of each node
        percentiles = 100.0 * order / max(1, len(ranks) - 1)
        for i, node in enumerate(g):
            self.metrics[node] = {
                "pagerank": float(pagerank[node]),
                "pagerank_pct": round(float(percentiles[i]), 1),
                "hub": float(hubs.get(node, 0.0)),
                "authority": float(authorities.get(node, 0.0)),
                "in_citations": g.in_degree(node),
                "out_citations": g.out_degree(node),
                "community": communities.get(node, -1),
            }

    def _build_coauthors(self) -> None:
        names: dict[str, Counter] = defaultdict(Counter)
        papers: dict[str, list[str]] = defaultdict(list)
        for doc_id, doc in self.docs.items():
            keys = []
            for name in (doc.get("authors") or [])[:MAX_AUTHORS_PER_PAPER]:
                key = author_key(name)
                if key:
                    names[key][name] += 1
                    papers[key].append(doc_id)
                    keys.append(key)
            keys = list(dict.fromkeys(keys))
            for i, a in enumerate(keys):
                for b in keys[i + 1:]:
                    weight = self.coauthors.get_edge_data(a, b, {}).get("weight", 0)
                    self.coauthors.add_edge(a, b, weight=weight + 1)
        for key in papers:
            self.coauthors.add_node(key)
        self.author_docs = dict(papers)

        pagerank = nx.pagerank(self.coauthors, weight="weight") if self.coauthors.number_of_edges() else {}
        for key, doc_ids in papers.items():
            citations = [self.metrics.get(d, {}).get("in_citations", 0) for d in doc_ids]
            years = [self.docs[d].get("year") for d in doc_ids if self.docs[d].get("year")]
            self.author_metrics[key] = {
                "name": names[key].most_common(1)[0][0],
                "papers": len(doc_ids),
                "citations": int(sum(citations)),
                "h_index": h_index(citations),
                "coauthors": self.coauthors.degree(key),
                "collaborations": int(self.coauthors.degree(key, weight="weight")),
                "pagerank": float(pagerank.get(key, 0.0)),
                "first_year": min(years) if years else None,
                "last_year": max(years) if years else None,
            }

    # ------------------------------------------------------------------ replication

    def to_payload(self) -> dict:
        return {
            "docs": self.docs,
            "edges": list(self.citations.edges()),
            "metrics": self.metrics,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "KnowledgeGraph":
        graph = cls()
        graph.docs = payload.get("docs", {})
        graph.citations.add_nodes_from(graph.docs)
        graph.citations.add_edges_from(tuple(e) for e in payload.get("edges", []))
        graph.metrics = payload.get("metrics", {})
        graph._build_coauthors()
        return graph

    # ------------------------------------------------------------------ queries

    def _node(self, doc_id: str, role: str, depth: int = 0) -> dict:
        doc = self.docs.get(doc_id, {})
        metrics = self.metrics.get(doc_id, {})
        return {
            "id": doc_id,
            "type": "paper",
            "role": role,
            "label": doc.get("title", doc_id),
            "year": doc.get("year"),
            "cluster": doc.get("cluster"),
            "community": metrics.get("community", -1),
            "pagerank": metrics.get("pagerank", 0.0),
            "pagerank_pct": metrics.get("pagerank_pct", 0.0),
            "citations": metrics.get("in_citations", 0),
            "depth": depth,
        }

    def _top(self, ids: Iterable[str], limit: int) -> list[str]:
        return sorted(ids, key=lambda d: self.metrics.get(d, {}).get("pagerank", 0.0), reverse=True)[:limit]

    def neighborhood(self, doc_id: str, depth: int = 1, per_side: int = 25,
                     include_authors: bool = True) -> dict:
        """Connection graph around one paper: references, citing papers, authors."""
        if doc_id not in self.citations:
            return {"nodes": [], "links": []}
        g = self.citations
        nodes = {doc_id: self._node(doc_id, "focus")}
        links: list[dict] = []
        frontier = [doc_id]
        for level in range(1, depth + 1):
            budget = per_side if level == 1 else max(4, per_side // 4)
            next_frontier = []
            for current in frontier:
                for neighbor in self._top(g.successors(current), budget):
                    if neighbor not in nodes:
                        nodes[neighbor] = self._node(neighbor, "reference" if level == 1 else "context", level)
                        next_frontier.append(neighbor)
                    links.append({"source": current, "target": neighbor, "type": "cites"})
                for neighbor in self._top(g.predecessors(current), budget):
                    if neighbor not in nodes:
                        nodes[neighbor] = self._node(neighbor, "citing" if level == 1 else "context", level)
                        next_frontier.append(neighbor)
                    links.append({"source": neighbor, "target": current, "type": "cites"})
            frontier = next_frontier[: per_side * 2]

        # Edges between the visible neighbours make the picture honest.
        visible = set(nodes)
        seen = {(link["source"], link["target"]) for link in links}
        for a in visible:
            for b in g.successors(a):
                if b in visible and (a, b) not in seen:
                    links.append({"source": a, "target": b, "type": "cites"})
                    seen.add((a, b))

        if include_authors:
            for name in (self.docs[doc_id].get("authors") or [])[:12]:
                key = author_key(name)
                author_id = f"author:{key}"
                nodes[author_id] = {
                    "id": author_id, "type": "author", "role": "author", "label": name,
                    "papers": self.author_metrics.get(key, {}).get("papers", 1), "depth": 1,
                }
                links.append({"source": author_id, "target": doc_id, "type": "wrote"})
        return {"nodes": list(nodes.values()), "links": links}

    def citation_network(self, limit: int = 250, cluster: int | None = None,
                         year_from: int | None = None, year_to: int | None = None) -> dict:
        """The most influential papers (by PageRank) and the citations among them."""
        def keep(doc_id: str) -> bool:
            doc = self.docs.get(doc_id, {})
            year = doc.get("year")
            if cluster is not None and doc.get("cluster") != cluster:
                return False
            if year_from is not None and (year is None or year < year_from):
                return False
            if year_to is not None and (year is None or year > year_to):
                return False
            return True

        chosen = self._top((d for d in self.citations if keep(d)), limit)
        chosen_set = set(chosen)
        nodes = [self._node(d, "paper") for d in chosen]
        links = [{"source": a, "target": b, "type": "cites"}
                 for a, b in self.citations.subgraph(chosen_set).edges()]
        return {"nodes": nodes, "links": links}

    def collaboration_network(self, limit: int = 150) -> dict:
        ranked = sorted(self.author_metrics, key=lambda k: (self.author_metrics[k]["pagerank"],
                                                             self.author_metrics[k]["papers"]), reverse=True)
        chosen = set(ranked[:limit])
        nodes = [{"id": f"author:{k}", "type": "author", "label": self.author_metrics[k]["name"],
                  **{m: self.author_metrics[k][m] for m in ("papers", "citations", "h_index", "pagerank")}}
                 for k in ranked[:limit]]
        links = [{"source": f"author:{a}", "target": f"author:{b}", "weight": d.get("weight", 1)}
                 for a, b, d in self.coauthors.subgraph(chosen).edges(data=True)]
        return {"nodes": nodes, "links": links}

    def author(self, name: str) -> dict | None:
        key = author_key(name)
        if key not in self.author_metrics:
            return None
        coauthors = sorted(self.coauthors[key].items(), key=lambda item: -item[1].get("weight", 1))
        return {
            "key": key,
            **self.author_metrics[key],
            "doc_ids": self.author_docs.get(key, []),
            "coauthor_list": [
                {"name": self.author_metrics[k]["name"], "weight": d.get("weight", 1),
                 "papers": self.author_metrics[k]["papers"]}
                for k, d in coauthors[:40]
            ],
        }

    def shortest_path(self, source: str, target: str) -> list[str] | None:
        if source not in self.citations or target not in self.citations:
            return None
        try:
            return nx.shortest_path(self.citations.to_undirected(as_view=True), source, target)
        except nx.NetworkXNoPath:
            return None

    def top_papers(self, limit: int = 10, cluster: int | None = None) -> list[dict]:
        ids = (d for d in self.citations if cluster is None or self.docs.get(d, {}).get("cluster") == cluster)
        return [self._node(d, "paper") | {"authors": self.docs[d].get("authors", [])[:4]}
                for d in self._top(ids, limit)]

    def top_authors(self, limit: int = 10) -> list[dict]:
        ranked = sorted(self.author_metrics.values(), key=lambda m: (m["citations"], m["papers"]), reverse=True)
        return ranked[:limit]

    def stats(self) -> dict:
        g = self.citations
        if g.number_of_nodes() == 0:
            return {"papers": 0, "citations": 0, "authors": 0, "collaborations": 0}
        components = nx.number_weakly_connected_components(g)
        largest = max((len(c) for c in nx.weakly_connected_components(g)), default=0)
        communities = len({m["community"] for m in self.metrics.values() if m["community"] >= 0})
        return {
            "papers": g.number_of_nodes(),
            "citations": g.number_of_edges(),
            "density": nx.density(g),
            "components": components,
            "largest_component": largest,
            "isolated": sum(1 for n in g if g.degree(n) == 0),
            "communities": communities,
            "authors": self.coauthors.number_of_nodes(),
            "collaborations": self.coauthors.number_of_edges(),
        }

    def degree_distribution(self) -> dict[int, int]:
        return dict(Counter(d for _, d in self.citations.in_degree()))
