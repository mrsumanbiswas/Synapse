"""Distributed query execution.

A search is broadcast to every live node at once (one thread per node). Each
shard answers with its best documents per ranking; because every node uses the
same global model, scores are comparable and the lists can simply be merged.
Hybrid mode then fuses the keyword (TF-IDF) and semantic (LSA) rankings with
reciprocal rank fusion: ``score(d) = Σ 1 / (60 + rank_list(d))``.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict

from ..index.query_parser import QuerySyntaxError, parse_query
from ..p2p.cluster import Cluster, NodeResult
from .shard import ShardEngine

MODES = ("hybrid", "keyword", "semantic", "boolean")
SORTS = ("relevance", "year_desc", "year_asc", "citations", "pagerank")
RRF_K = 60


def reciprocal_rank_fusion(*rankings: list[list]) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (doc_id, _) in enumerate(ranking):
            scores[doc_id] += 1.0 / (RRF_K + rank + 1)
    return sorted(scores.items(), key=lambda item: -item[1])


def merge_ranked(results: dict[str, NodeResult], key: str) -> list[list]:
    merged = [item for r in results.values() if r.ok for item in r.payload.get(key, [])]
    return sorted(merged, key=lambda item: -item[1])


class QueryEngine:
    def __init__(self, cluster: Cluster, engine: ShardEngine):
        self.cluster = cluster
        self.engine = engine

    def _topic_label(self, cluster_id: int | None) -> dict | None:
        topic = self.engine.model.topic(cluster_id) if self.engine.model else None
        return {"id": topic["id"], "label": topic["label"]} if topic else None

    def _decorate(self, card: dict, score: float | None = None, rank: int | None = None) -> dict:
        out = dict(card)
        out["topic"] = self._topic_label(card.get("cluster"))
        if score is not None:
            out["score"] = round(score, 6)
        if rank is not None:
            out["rank"] = rank
        return out

    def search(self, query: str, mode: str = "hybrid", page: int = 1, size: int = 10,
               sort: str = "relevance", filters: dict | None = None) -> dict:
        started = time.perf_counter()
        mode = mode if mode in MODES else "hybrid"
        sort = sort if sort in SORTS else "relevance"
        parsed = parse_query(query, strict=(mode == "boolean"))  # raises QuerySyntaxError for bad boolean syntax
        page = max(1, page)
        size = max(1, min(size, 50))
        k = min(page * size, 500)

        results = self.cluster.broadcast("SEARCH", {
            "query": query, "mode": mode, "k": k, "sort": sort, "filters": filters or {}, "facets": True,
        }, timeout=25)

        docs: dict[str, dict] = {}
        facets = {"years": Counter(), "topics": Counter(), "authors": Counter(), "sources": Counter()}
        totals = Counter()
        model_versions = set()
        for result in results.values():
            if not result.ok:
                continue
            payload = result.payload
            docs.update(payload.get("docs", {}))
            for name, counts in (payload.get("facets") or {}).items():
                facets[name].update({k2: v for k2, v in counts.items()})
            for key in ("total", "total_keyword", "total_semantic"):
                totals[key] += payload.get(key, 0)
            model_versions.add(payload.get("model_version"))

        if sort != "relevance":
            ranked = [(d, s) for d, s in merge_ranked(results, "sorted")]
            total = totals["total"]
        else:
            keyword = merge_ranked(results, "keyword")
            semantic = merge_ranked(results, "semantic")
            if mode in ("keyword", "boolean"):
                ranked, total = [(d, s) for d, s in keyword], totals["total_keyword"]
            elif mode == "semantic":
                ranked, total = [(d, s) for d, s in semantic], totals["total_semantic"]
            else:
                ranked, total = reciprocal_rank_fusion(keyword, semantic), totals["total"]

        offset = (page - 1) * size
        hits = [self._decorate(docs[d], score, offset + i + 1)
                for i, (d, score) in enumerate(ranked[offset : offset + size]) if d in docs]

        suggestion = None
        if total < 3 and mode != "boolean" and query.strip():
            suggestion = self.engine.spelling(query)
        concepts = []
        if mode in ("semantic", "hybrid"):
            concepts = self.concepts(query)

        topic_facets = []
        for topic_id, count in facets["topics"].most_common():
            label = self._topic_label(int(topic_id))
            if label:
                topic_facets.append({**label, "count": count})

        return {
            "query": query,
            "mode": mode,
            "sort": sort,
            "page": page,
            "size": size,
            "total": total,
            "results": hits,
            "facets": {
                "years": sorted(([int(y), c] for y, c in facets["years"].items()), key=lambda item: item[0]),
                "topics": topic_facets,
                "authors": [[a, c] for a, c in facets["authors"].most_common(15)],
                "sources": [[s, c] for s, c in facets["sources"].most_common()],
            },
            "nodes": [{**r.summary(), "hits": r.payload.get("total", 0) if r.ok else 0} for r in results.values()],
            "did_you_mean": suggestion,
            "concepts": concepts,
            "parsed": {"normalized": str(parsed.ast), "fallback": parsed.fallback, "error": parsed.error,
                       "operators": parsed.has_operators},
            "model_versions": sorted(v for v in model_versions if v is not None),
            "took_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def concepts(self, query: str, limit: int = 10) -> list[dict]:
        """The LSA concept terms a query maps to: why "car" also finds "vehicle"."""
        engine = self.engine
        parsed = parse_query(query)
        stems, _ = engine._query_terms(parsed)
        vector = engine._query_concepts(stems)
        if vector is None or engine.model is None or engine.model.lsa is None:
            return []
        own = set(stems)
        out = []
        for i, weight in engine.model.lsa.top_terms(vector, limit + len(own)):
            term = engine.model.vsm.terms[i]
            if term in own:
                continue
            out.append({"term": engine.model.display(term), "weight": round(weight, 4)})
        return out[:limit]

    def compare(self, query: str, size: int = 10) -> dict:
        """The same query ranked by TF-IDF and by LSA, side by side."""
        results = self.cluster.broadcast("SEARCH", {"query": query, "mode": "hybrid", "k": size, "facets": False},
                                         timeout=25)
        docs: dict[str, dict] = {}
        for result in results.values():
            if result.ok:
                docs.update(result.payload.get("docs", {}))
        keyword = merge_ranked(results, "keyword")[:size]
        semantic = merge_ranked(results, "semantic")[:size]
        keyword_ids = {d for d, _ in keyword}
        semantic_ids = {d for d, _ in semantic}
        return {
            "query": query,
            "keyword": [self._decorate(docs[d], s, i + 1) for i, (d, s) in enumerate(keyword) if d in docs],
            "semantic": [self._decorate(docs[d], s, i + 1) | {"also_keyword": d in keyword_ids}
                         for i, (d, s) in enumerate(semantic) if d in docs],
            "overlap": len(keyword_ids & semantic_ids),
            "concepts": self.concepts(query),
        }

    def explain(self, query: str) -> dict:
        """Tokens, RPN and the parse tree, plus the operand-stack trace summed over shards."""
        parsed = parse_query(query, strict=True)
        results = self.cluster.broadcast("EXPLAIN", {"query": query}, timeout=20)
        steps: list[dict] = []
        matches = 0
        for result in results.values():
            if not result.ok:
                continue
            matches += result.payload["matches"]
            for i, step in enumerate(result.payload["steps"]):
                if i < len(steps):
                    steps[i]["size"] += step["size"]  # shards are disjoint, so set sizes add up
                else:
                    steps.append(dict(step))
        return {**parsed.to_dict(), "steps": steps, "matches": matches,
                "nodes": [r.summary() for r in results.values()]}

    def similar(self, doc_id: str, vector: list[float] | None, k: int = 8) -> list[dict]:
        if not vector:
            return []
        results = self.cluster.broadcast("VECTOR_SEARCH", {"vector": vector, "k": k, "exclude": [doc_id]}, timeout=15)
        docs: dict[str, dict] = {}
        for result in results.values():
            if result.ok:
                docs.update(result.payload.get("docs", {}))
        ranked = merge_ranked(results, "results")[:k]
        return [self._decorate(docs[d], s) for d, s in ranked if d in docs]


__all__ = ["QueryEngine", "QuerySyntaxError", "reciprocal_rank_fusion", "MODES", "SORTS"]
