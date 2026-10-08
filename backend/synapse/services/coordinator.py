"""Cluster-wide model rebuilds. Any node can lead one; the newest version wins.

    1. MODEL_STATS        every shard reports document frequencies and its lexicon
    2. MODEL_SAMPLE       every shard sends a sample of term vectors + citation records
    3. (leader)           vocabulary/IDF, truncated SVD (LSA), k-means topics, PCA axes
       MODEL_INSTALL      the model is broadcast; shards vectorise their documents and
                          report each document's topic
    4. (leader)           citation graph, PageRank/HITS, communities, co-authorship,
                          topic timeline, Kleinberg bursts, temporal concept graph
       ANALYTICS_INSTALL  the results are broadcast so any node can answer graph queries
"""

from __future__ import annotations

import logging
import math
import threading
import time
import zlib
from collections import Counter, defaultdict

import json

import numpy as np

from ..config import Settings
from ..graph import temporal
from ..graph.knowledge_graph import KnowledgeGraph
from ..p2p.cluster import Cluster
from ..text.stemmer import stem
from ..text.extract import normalize_title
from ..text.tokenizer import GENERIC_STEMS, phrases
from ..vector.clustering import kmeans, pca
from ..vector.lsa import LatentSemanticModel
from ..vector.vsm import VectorSpaceModel
from .model import GlobalModel

log = logging.getLogger(__name__)
TITLE_STOP = {"the", "and", "for", "with", "from", "into", "using", "based", "via", "toward", "towards"}


class ModelCoordinator:
    def __init__(self, settings: Settings, cluster: Cluster, history_store=None):
        self.settings = settings
        self.cluster = cluster
        self._lock = threading.Lock()
        self._pending = False
        self.running = False
        self._store = history_store
        self.history: list[dict] = history_store.get_meta("rebuild_history", []) if history_store else []

    # ------------------------------------------------------------------ entry points

    def rebuild(self, reason: str) -> dict:
        """Run a rebuild now; if one is already running, queue exactly one more."""
        if not self._lock.acquire(blocking=False):
            self._pending = True
            return {"status": "queued", "reason": reason}
        try:
            self.running = True
            while True:
                self._pending = False
                try:
                    result = self._rebuild(reason)
                except Exception as exc:  # noqa: BLE001
                    log.exception("model rebuild failed")
                    result = {"status": "failed", "error": str(exc), "reason": reason, "finished_at": time.time()}
                self.history = ([result] + self.history)[:20]
                if self._store is not None:
                    self._store.set_meta("rebuild_history", self.history)
                if not self._pending:
                    return result
                reason = "changes arrived during the previous rebuild"
        finally:
            self.running = False
            self._lock.release()

    def rebuild_in_background(self, reason: str) -> None:
        threading.Thread(target=self.rebuild, args=(reason,), name="rebuild", daemon=True).start()

    # ------------------------------------------------------------------ phases

    def _rebuild(self, reason: str) -> dict:
        timings: dict[str, float] = {}
        clock = time.perf_counter()
        version = int(time.time() * 1000)

        stats = {n: r for n, r in self.cluster.broadcast("MODEL_STATS", {}, timeout=120).items() if r.ok}
        nodes = sorted(stats)
        n_docs = sum(r.payload["n_docs"] for r in stats.values())
        timings["collect_stats"] = time.perf_counter() - clock
        if n_docs == 0:
            return {"status": "empty", "reason": reason, "nodes": nodes, "finished_at": time.time()}

        df: Counter = Counter()
        surfaces: dict[str, tuple[str, int]] = {}
        lexicon = {kind: Counter() for kind in ("word", "phrase", "author")}
        for result in stats.values():
            df.update(result.payload["df"])
            for term, (word, count) in result.payload["surface"].items():
                if term not in surfaces or count > surfaces[term][1]:
                    surfaces[term] = (word, count)
            for kind in lexicon:
                lexicon[kind].update(dict(result.payload["lexicon"][kind]))
        vsm = VectorSpaceModel.from_document_frequencies(df, n_docs)

        clock = time.perf_counter()
        per_node = max(200, self.settings.sample_limit // max(1, len(nodes)))
        samples = self.cluster.broadcast("MODEL_SAMPLE", {"limit": per_node, "seed": version % 100_000},
                                         nodes=nodes, timeout=180)
        sample_docs, graph_docs = [], []
        for result in samples.values():
            if result.ok:
                sample_docs.extend(result.payload["sample"])
                graph_docs.extend(result.payload["graph"])
        timings["collect_sample"] = time.perf_counter() - clock

        clock = time.perf_counter()
        matrix = vsm.vectorize([d["tf"] for d in sample_docs], [d["titles"] for d in sample_docs])
        lsa = LatentSemanticModel.fit(matrix, self.settings.lsa_dims)
        timings["svd"] = time.perf_counter() - clock
        concepts = lsa.transform(matrix) if lsa is not None else None
        surface = {term: surfaces.get(term, (term, 0))[0] for term in vsm.terms}

        clock = time.perf_counter()
        centroids = labels = None
        topics: list[dict] = []
        pca_mean = pca_components = None
        if concepts is not None and len(sample_docs) >= 10:
            n_topics = int(min(self.settings.topics, max(2, len(sample_docs) // 25)))
            centroids, labels = kmeans(concepts, n_topics)
            pca_mean, pca_components = pca(concepts, 3)
            topics = self._label_topics(centroids, labels, sample_docs, lsa, vsm, surface)
        timings["clustering"] = time.perf_counter() - clock

        model = GlobalModel(
            version=version, leader=self.settings.node_id, built_at=time.time(), n_docs=n_docs, vsm=vsm, lsa=lsa,
            centroids=centroids, pca_mean=pca_mean, pca_components=pca_components, topics=topics, surface=surface,
            lexicon={
                "word": lexicon["word"].most_common(40_000),
                "phrase": [(p, c) for p, c in lexicon["phrase"].most_common(25_000) if c > 1],
                "author": lexicon["author"].most_common(30_000),
            },
            stats={"sample_size": len(sample_docs), "nodes": nodes, "reason": reason},
        )

        clock = time.perf_counter()
        blob = model.to_bytes()
        installs = self.cluster.broadcast("MODEL_INSTALL", {}, blob=blob, nodes=nodes, timeout=300)
        assignments: dict[str, int] = {}
        for result in installs.values():
            if result.ok and result.payload.get("accepted"):
                assignments.update(result.payload["assignments"])
        timings["install_model"] = time.perf_counter() - clock

        clock = time.perf_counter()
        analytics = self._analytics(version, model, graph_docs, assignments, sample_docs, concepts, lsa, vsm, surface)
        timings["analytics"] = time.perf_counter() - clock
        clock = time.perf_counter()
        packed = zlib.compress(json.dumps(analytics).encode(), 6)
        self.cluster.broadcast("ANALYTICS_INSTALL", {}, blob=packed, nodes=nodes, timeout=300)
        timings["install_analytics"] = time.perf_counter() - clock

        result = {
            "status": "ok", "reason": reason, "version": version, "leader": self.settings.node_id, "nodes": nodes,
            "documents": n_docs, "sample": len(sample_docs), "vocabulary": len(vsm),
            "concepts": lsa.k if lsa else 0, "topics": len(topics),
            "citations": analytics["graph_stats"].get("citations", 0),
            "model_bytes": len(blob), "analytics_bytes": len(packed),
            "timings": {k: round(v * 1000, 1) for k, v in timings.items()},
            "finished_at": time.time(),
        }
        log.info("rebuild v%d done: %d docs on %d nodes, %d terms, %d concepts, %d topics, %d citations",
                 version, n_docs, len(nodes), len(vsm), result["concepts"], len(topics), result["citations"])
        return result

    # ------------------------------------------------------------------ labels

    @staticmethod
    def _title_label(member_titles: list[str], top_terms: list[str], used: set[str]) -> str | None:
        wanted = set(top_terms[:12])
        scored: Counter = Counter()
        for title in member_titles:
            for bigram in set(phrases(title)):
                words = bigram.split()
                if any(w in TITLE_STOP for w in words):
                    continue
                overlap = sum(1 for w in words if stem(w) in wanted)
                if overlap:
                    scored[bigram] += overlap
        for bigram, score in scored.most_common(8):
            label = bigram.title()
            if score >= 3 and label not in used:
                return label
        return None

    def _label_topics(self, centroids: np.ndarray, labels: np.ndarray, sample_docs: list[dict],
                      lsa: LatentSemanticModel, vsm: VectorSpaceModel, surface: dict[str, str]) -> list[dict]:
        topics, used = [], set()
        for c, centroid in enumerate(centroids):
            members = np.where(labels == c)[0]
            terms = [vsm.terms[i] for i, _ in lsa.top_terms(centroid, 25) if vsm.terms[i] not in GENERIC_STEMS]
            label = self._title_label([sample_docs[i]["title"] for i in members], terms, used)
            if label is None:
                label = " & ".join(surface.get(t, t).title() for t in terms[:2]) or f"Topic {c + 1}"
            used.add(label)
            topics.append({"id": c, "label": label, "terms": [surface.get(t, t) for t in terms[:10]],
                           "sample_size": int(len(members))})
        return topics

    # ------------------------------------------------------------------ analytics

    @staticmethod
    def _resolve_citations(graph_docs: list[dict]) -> tuple[list[tuple[str, str]], dict[str, dict[str, str]]]:
        """Match references to documents. Returns the edges and the approximate matches
        (``{citing_id: {reference_position: cited_id}}``) so the UI can show them too."""
        owner: dict[str, str] = {}
        titles: dict[str, str] = {}
        title_tokens: dict[str, set[str]] = defaultdict(set)
        tokens_of: dict[str, set[str]] = {}
        for doc in graph_docs:
            for key in doc["keys"]:
                owner.setdefault(key, doc["id"])
                if key.startswith("title:"):
                    title = key[6:]
                    titles.setdefault(title, doc["id"])
                    tokens = {t for t in title.split() if len(t) > 2}
                    tokens_of[doc["id"]] = tokens
                    for token in tokens:
                        title_tokens[token].add(doc["id"])

        def approximate(raw_title: str | None, title: str) -> str | None:
            # 1. "Dynamo: Amazon's highly available key-value store" -> a corpus title "Dynamo"
            if raw_title and ":" in raw_title:
                head = normalize_title(raw_title.split(":", 1)[0])
                if head and head in titles:
                    return titles[head]
            # 2. a corpus title (3+ words) that the reference title starts with
            words = title.split()
            for k in range(len(words) - 1, 2, -1):
                prefix = " ".join(words[:k])
                if prefix in titles:
                    return titles[prefix]
            # 3. token Jaccard similarity among documents sharing the rarest words
            tokens = {t for t in words if len(t) > 2}
            rare = sorted(tokens, key=lambda t: len(title_tokens.get(t, ())))[:3]
            candidates = set().union(*(title_tokens.get(t, set()) for t in rare)) if rare else set()
            best, best_score = None, 0.0
            for candidate in candidates:
                other = tokens_of.get(candidate, set())
                score = len(tokens & other) / max(1, len(tokens | other))
                if score > best_score:
                    best, best_score = candidate, score
            return best if best_score >= 0.75 else None

        edges: set[tuple[str, str]] = set()
        approximate_matches: dict[str, dict[str, str]] = {}
        for doc in graph_docs:
            for ref in doc["refs"]:
                target = next((owner[k] for k in ref["k"] if k in owner), None)
                if target is None:
                    title = next((k[6:] for k in ref["k"] if k.startswith("title:")), None)
                    if title:
                        target = approximate(ref.get("t"), title)
                        if target and target != doc["id"]:
                            approximate_matches.setdefault(doc["id"], {})[str(ref["p"])] = target
                if target is not None and target != doc["id"]:
                    edges.add((doc["id"], target))
        return sorted(edges), approximate_matches

    def _analytics(self, version: int, model: GlobalModel, graph_docs: list[dict], assignments: dict[str, int],
                   sample_docs: list[dict], concepts: np.ndarray | None, lsa: LatentSemanticModel | None,
                   vsm: VectorSpaceModel, surface: dict[str, str]) -> dict:
        edges, approximate = self._resolve_citations(graph_docs)
        light = [{"id": d["id"], "title": d["title"], "year": d["year"], "cluster": assignments.get(d["id"]),
                  "authors": d["authors"][:12], "node": d["id"].split(":", 1)[0]} for d in graph_docs]
        graph = KnowledgeGraph.build(light, edges)

        years = [d["year"] for d in graph_docs]
        clusters = [assignments.get(d["id"], -1) for d in graph_docs]
        n_topics = len(model.topics)
        axis = temporal.year_axis(years)
        timeline = temporal.timeline(years, clusters, n_topics, axis) if axis else {"years": [], "counts": [], "totals": []}

        sizes = Counter(c for c in clusters if c >= 0)
        recent = set(axis[-5:]) if axis else set()
        recent_total = sum(1 for y in years if y in recent) or 1
        total = len(graph_docs) or 1
        topics = []
        for topic in model.topics:
            c = topic["id"]
            size = sizes.get(c, 0)
            recent_count = sum(1 for y, k in zip(years, clusters) if k == c and y in recent)
            share = size / total
            growth = (recent_count / recent_total) / share if share else 0.0
            topics.append({**topic, "size": size, "share": round(share, 4), "recent": recent_count,
                           "growth": round(growth, 3),
                           "top_papers": [{"id": p["id"], "title": p["label"], "year": p["year"]}
                                          for p in graph.top_papers(5, cluster=c)]})

        topic_bursts = []
        if axis:
            labels = {t["id"]: t["label"] for t in model.topics}
            series = {labels[c]: timeline["counts"][c] for c in range(n_topics)}
            topic_bursts = temporal.find_bursts(series, timeline["totals"], axis, "topic")
        term_bursts = self._term_bursts(sample_docs, axis, vsm, surface)

        evolution = {"eras": [], "nodes": [], "links": [], "events": []}
        if concepts is not None and lsa is not None and len(sample_docs) >= 60:
            titles = [d["title"] for d in sample_docs]

            def era_label(centroid: np.ndarray, members: np.ndarray) -> str:
                terms = [vsm.terms[i] for i, _ in lsa.top_terms(centroid, 25) if vsm.terms[i] not in GENERIC_STEMS]
                label = self._title_label([titles[i] for i in members], terms, set())
                return label or " & ".join(surface.get(t, t).title() for t in terms[:2])

            evolution = temporal.evolution_graph([d["year"] for d in sample_docs], concepts, era_label)

        return {
            "version": version,
            "built_at": time.time(),
            "leader": self.settings.node_id,
            "graph": graph.to_payload(),
            "graph_stats": graph.stats(),
            "degree_distribution": graph.degree_distribution(),
            "topics": topics,
            "timeline": timeline,
            "bursts": {"topics": topic_bursts[:30], "terms": term_bursts[:40]},
            "evolution": evolution,
            "top_papers": graph.top_papers(25),
            "top_authors": graph.top_authors(25),
            "keys": {key: d["id"] for d in graph_docs for key in d["keys"]},
            "approximate_references": approximate,
        }

    @staticmethod
    def _term_bursts(sample_docs: list[dict], axis: list[int], vsm: VectorSpaceModel,
                     surface: dict[str, str]) -> list[dict]:
        if not axis:
            return []
        index = {year: i for i, year in enumerate(axis)}
        df: Counter = Counter()
        for doc in sample_docs:
            df.update(doc["tf"].keys())
        floor = max(5, int(math.sqrt(len(sample_docs)) / 4))
        candidates = {t for t, f in df.items() if f >= floor and t in vsm.index and t not in GENERIC_STEMS and t.isalpha()}
        series = {t: [0] * len(axis) for t in candidates}
        totals = [0] * len(axis)
        for doc in sample_docs:
            i = index.get(doc["year"])
            if i is None:
                continue
            totals[i] += 1
            for term in doc["tf"]:
                if term in series:
                    series[term][i] += 1
        bursts = temporal.find_bursts(series, totals, axis, "term", min_weight=4.0)
        for burst in bursts:
            burst["label"] = surface.get(burst["label"], burst["label"])
        return bursts
