"""The shard engine: one node's documents, indexes and vectors, and the RPC handlers.

State held in memory (rebuilt from SQLite at start-up):

* ``index``    positional inverted index over this shard's documents
* ``meta``     per-document metadata used for filters, facets and sorting
* ``vectors``  TF-IDF rows (scipy.sparse) and LSA concept vectors (numpy)
* ``model``    the replicated global model (vocabulary, IDF, concepts, topics)
* ``graph``    the replicated knowledge graph (citations, co-authorship)
* tries        autocomplete over words, phrases and author names
"""

from __future__ import annotations

import gzip
import json
import logging
import random
import threading
import time
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from ..config import Settings
from ..graph.knowledge_graph import KnowledgeGraph, author_key
from ..index.inverted_index import FIELD_GAP, InvertedIndex
from ..index.query_parser import (
    ALL, EMPTY, ParsedQuery, Phrase, Resolver, evaluate, parse_query, year_bounds,
)
from ..index.trie import Trie
from ..ingest.analysis import AnalyzedDocument, analyze_record
from ..ingest.records import RawRecord
from ..storage.shard_store import ShardStore
from ..text.tokenizer import analyze, fold
from ..vector.clustering import assign, project
from .model import GlobalModel
from .snippets import make_snippet

log = logging.getLogger(__name__)

SEMANTIC_FLOOR = 0.15
SORT_KEYS = ("relevance", "year_desc", "year_asc", "citations", "pagerank")
CARD_FIELDS = ("id", "title", "authors", "year", "venue", "doi", "url", "source", "cited_by_count", "cluster",
               "pagerank", "pagerank_pct", "in_citations", "out_citations", "external_id", "filename")


@dataclass
class Vectors:
    ids: list[str]
    row: dict[str, int]
    tfidf: sparse.csr_matrix | None
    concepts: np.ndarray | None
    coords: np.ndarray | None

    @classmethod
    def empty(cls) -> "Vectors":
        return cls([], {}, None, None, None)


class ShardEngine:
    def __init__(self, settings: Settings, store: ShardStore):
        self.settings = settings
        self.node_id = settings.node_id
        self.store = store
        self.lock = threading.RLock()
        self.index = InvertedIndex()
        self.meta: dict[str, dict] = {}
        self.author_names: dict[str, set[str]] = {}
        self.author_tokens: dict[str, set[str]] = {}
        self.lexicon: dict[str, Counter] = {k: Counter() for k in ("word", "phrase", "author", "surface")}
        self.model: GlobalModel | None = None
        self.vectors = Vectors.empty()
        self.analytics: dict | None = None
        self.graph: KnowledgeGraph | None = None
        self.words = Trie()
        self.phrases = Trie()
        self.authors = Trie()
        self._tries_dirty = True
        self.analysis_pool = ThreadPoolExecutor(max_workers=max(1, settings.ingest_workers),
                                                thread_name_prefix="analyze")
        self.loaded_in_ms = 0.0

    # ================================================================== start-up

    def load(self) -> None:
        started = time.perf_counter()
        for item in self.store.iter_meta():
            self._remember(item["id"], item)

        current, positions, titles = None, {}, []
        for doc_id, term, in_title, plist in self.store.iter_postings():
            if doc_id != current:
                self._add_loaded(current, positions, titles)
                current, positions, titles = doc_id, {}, []
            positions[term] = plist
            if in_title:
                titles.append(term)
        self._add_loaded(current, positions, titles)

        for kind, text, count in self.store.iter_lexicon():
            if kind in self.lexicon:
                self.lexicon[kind][text] = count

        model_path = self.settings.data_dir / "model.npz"
        if model_path.exists():
            try:
                self._install_model(GlobalModel.from_bytes(model_path.read_bytes()), persist=False)
            except Exception:  # noqa: BLE001 - a broken cache must not stop the node
                log.exception("could not load the cached model; it will be rebuilt")
        analytics_path = self.settings.data_dir / "analytics.json.gz"
        if analytics_path.exists():
            try:
                with gzip.open(analytics_path, "rt", encoding="utf-8") as fh:
                    self._install_analytics(json.load(fh), persist=False)
            except Exception:  # noqa: BLE001
                log.exception("could not load cached analytics")
        self._rebuild_tries()
        self.loaded_in_ms = (time.perf_counter() - started) * 1000
        log.info("shard %s loaded %d documents, %d terms in %.0f ms", self.node_id, len(self.meta),
                 len(self.index.postings), self.loaded_in_ms)

    def _add_loaded(self, doc_id: str | None, positions: dict, titles: list[str]) -> None:
        if doc_id is None or doc_id not in self.meta:
            return
        length = self.meta[doc_id].get("length") or sum(len(p) for p in positions.values())
        self.index.add_positions(doc_id, positions, length, titles)

    def _remember(self, doc_id: str, item: dict) -> None:
        authors = list(item.get("authors") or [])
        self.meta[doc_id] = {
            "title": item.get("title") or "",
            "year": item.get("year"),
            "venue": item.get("venue"),
            "source": item.get("source"),
            "doi": item.get("doi"),
            "cluster": item.get("cluster"),
            "pagerank": item.get("pagerank") or 0.0,
            "pagerank_pct": item.get("pagerank_pct") or 0.0,
            "in_citations": item.get("in_citations") or 0,
            "cited_by_count": item.get("cited_by_count"),
            "length": item.get("length") or 0,
            "ingested_at": item.get("ingested_at"),
            "job_id": item.get("job_id"),
            "authors": authors,
        }
        for name in authors:
            key = author_key(name)
            self.author_names.setdefault(key, set()).add(doc_id)
            for token in key.split():
                if len(token) > 1:
                    self.author_tokens.setdefault(token, set()).add(doc_id)

    def _forget(self, doc_id: str) -> None:
        meta = self.meta.pop(doc_id, None)
        if not meta:
            return
        for name in meta["authors"]:
            key = author_key(name)
            self.author_names.get(key, set()).discard(doc_id)
            for token in key.split():
                self.author_tokens.get(token, set()).discard(doc_id)

    # ================================================================== tries

    def _rebuild_tries(self) -> None:
        words, phrases, authors = Trie(), Trie(), Trie()
        lexicon = self.model.lexicon if self.model and self.model.lexicon else None
        word_items = lexicon["word"] if lexicon else self.lexicon["word"].most_common(40_000)
        phrase_items = lexicon["phrase"] if lexicon else [(p, c) for p, c in self.lexicon["phrase"].most_common(20_000) if c > 1]
        author_items = lexicon["author"] if lexicon else self.lexicon["author"].most_common(20_000)
        for word, count in word_items:
            words.insert(word, int(count))
        for phrase, count in phrase_items:
            phrases.insert(phrase, int(count))
        for name, count in author_items:
            key = author_key(name)
            authors.insert(key, int(count), value=name)
            parts = key.split()
            if len(parts) > 1:  # also let "hinton" find "Geoffrey E. Hinton"
                authors.insert(" ".join([parts[-1]] + parts[:-1]), int(count), value=name)
        self.words, self.phrases, self.authors = words, phrases, authors
        self._tries_dirty = False

    def _ensure_tries(self) -> None:
        if self._tries_dirty and not (self.model and self.model.lexicon):
            with self.lock:
                self._rebuild_tries()

    def autocomplete(self, text: str, limit: int = 8) -> list[dict]:
        self._ensure_tries()
        query = fold(text).lstrip()
        if not query.strip():
            return []
        words = query.split()
        last = "" if query.endswith(" ") else words[-1]
        head = " ".join(words[:-1] if last else words)
        out: list[dict] = []
        seen: set[str] = set()

        def add(value: str, kind: str, count: int) -> None:
            key = value.lower()
            if key not in seen and key != query.strip():
                seen.add(key)
                out.append({"text": value, "kind": kind, "count": int(count)})

        for phrase, count, _ in self.phrases.complete(query.strip(), limit):
            add(phrase, "phrase", count)
        if last:
            for word, count, _ in self.words.complete(last, limit):
                add(f"{head} {word}".strip(), "term", count)
        for _, count, display in self.authors.complete(query.strip(), 4):
            add(display, "author", count)
        if not out and last and len(last) >= 4:
            for word, _, count in self.words.fuzzy(last, 1 if len(last) < 7 else 2, 3):
                add(f"{head} {word}".strip(), "correction", count)
        return out[:limit]

    def spelling(self, query: str) -> str | None:
        """'Did you mean': swap unknown words for their closest frequent neighbour in the trie."""
        self._ensure_tries()
        changed, out = False, []
        for word in query.split():
            plain = fold(word)
            if plain.isalpha() and len(plain) >= 4 and plain not in self.words and word not in ("AND", "OR", "NOT"):
                candidates = self.words.fuzzy(plain, 2 if len(plain) > 6 else 1, 5)
                if candidates:
                    best = min(candidates, key=lambda c: (c[1], -c[2]))
                    out.append(best[0])
                    changed = True
                    continue
            out.append(word)
        return " ".join(out) if changed else None

    # ================================================================== ingest

    def _safe_analyze(self, record: RawRecord) -> AnalyzedDocument | Exception:
        try:
            if not record.title and not record.abstract and not record.body:
                raise ValueError("record has no text")
            return analyze_record(record, self.node_id)
        except Exception as exc:  # noqa: BLE001 - reported per record
            return exc

    def store_records(self, records: list[RawRecord], job_id: str | None, via: str | None) -> dict:
        """Parse, de-duplicate, persist and index a batch routed to this shard."""
        analyzed, failed = [], []
        for record, result in zip(records, self.analysis_pool.map(self._safe_analyze, records)):
            if isinstance(result, Exception):
                failed.append({"title": (record.title or record.filename or "?")[:160], "error": str(result)})
            else:
                analyzed.append(result)

        with self.lock:
            known = self.store.known_hashes([doc.content_hash for doc in analyzed])
            fresh, seen = [], set()
            for doc in analyzed:
                if doc.content_hash in known or doc.content_hash in seen:
                    continue
                seen.add(doc.content_hash)
                fresh.append(doc)
            if fresh:
                self.store.insert(fresh, job_id, via, FIELD_GAP)
                deltas = {k: Counter() for k in self.lexicon}
                for doc in fresh:
                    self.index.add(doc.id, doc.title_terms, doc.body_terms)
                    r = doc.record
                    self._remember(doc.id, {**r.to_dict(), "length": doc.length, "ingested_at": time.time(),
                                            "job_id": job_id, "cited_by_count": r.cited_by_count})
                    deltas["word"].update(doc.words)
                    deltas["phrase"].update(doc.phrases)
                    deltas["author"].update(a for a in r.authors if a)
                    deltas["surface"].update(f"{stem}\t{word}" for stem, word in doc.surfaces.elements())
                for kind, delta in deltas.items():
                    self.lexicon[kind].update(delta)
                    self.store.add_lexicon(kind, delta)
                self._fold_in([doc.id for doc in fresh])
                self._tries_dirty = True

        documents = [{
            "id": doc.id, "title": doc.record.title, "abstract": (doc.record.abstract or doc.record.body)[:700],
            "authors": doc.record.authors[:8], "year": doc.record.year, "venue": doc.record.venue,
            "filename": doc.record.filename, "node": self.node_id,
        } for doc in fresh]
        return {"stored": len(fresh), "duplicates": len(analyzed) - len(fresh), "failed": failed,
                "documents": documents}

    def delete(self, doc_id: str) -> bool:
        with self.lock:
            if not self.store.delete(doc_id):
                return False
            self.index.remove(doc_id)
            self._forget(doc_id)
            if self.model:
                self._vectorize_all()
            return True

    # ================================================================== vectors

    def _vectorize(self, ids: list[str]) -> tuple[sparse.csr_matrix, np.ndarray | None, np.ndarray | None, np.ndarray]:
        model = self.model
        tfs = [self.index.term_frequencies(d) for d in ids]
        titles = [self.index.title_terms.get(d, ()) for d in ids]
        tfidf = model.vsm.vectorize(tfs, titles)
        concepts = model.lsa.transform(tfidf) if model.lsa is not None else None
        coords = None
        if concepts is not None and model.pca_mean is not None:
            coords = project(concepts, model.pca_mean, model.pca_components)
        clusters = (assign(concepts, model.centroids) if concepts is not None and model.centroids is not None
                    and len(model.centroids) else np.zeros(len(ids), dtype=int))
        return tfidf, concepts, coords, clusters

    def _vectorize_all(self) -> None:
        ids = list(self.meta)
        if not ids or self.model is None:
            self.vectors = Vectors.empty()
            return
        tfidf, concepts, coords, clusters = self._vectorize(ids)
        self.vectors = Vectors(ids, {d: i for i, d in enumerate(ids)}, tfidf, concepts, coords)
        for doc_id, cluster in zip(ids, clusters):
            self.meta[doc_id]["cluster"] = int(cluster)

    def _fold_in(self, ids: list[str]) -> None:
        """LSA "folding-in": project new documents with the current model, no refit."""
        if self.model is None or not ids:
            return
        tfidf, concepts, coords, clusters = self._vectorize(ids)
        v = self.vectors
        start = len(v.ids)
        v.ids.extend(ids)
        v.row.update({d: start + i for i, d in enumerate(ids)})
        v.tfidf = tfidf if v.tfidf is None else sparse.vstack([v.tfidf, tfidf], format="csr")
        if concepts is not None:
            v.concepts = concepts if v.concepts is None else np.vstack([v.concepts, concepts])
        if coords is not None:
            v.coords = coords if v.coords is None else np.vstack([v.coords, coords])
        assignments = {doc_id: int(c) for doc_id, c in zip(ids, clusters)}
        for doc_id, cluster in assignments.items():
            self.meta[doc_id]["cluster"] = cluster
        self.store.update_clusters(assignments)

    def doc_vector(self, doc_id: str) -> np.ndarray | None:
        row = self.vectors.row.get(doc_id)
        if row is None or self.vectors.concepts is None:
            return None
        return self.vectors.concepts[row]

    # ================================================================== model sync

    def model_stats(self) -> dict:
        """Phase 1 of a rebuild: document frequencies and the local lexicon."""
        with self.lock:
            df = {term: len(docs) for term, docs in self.index.postings.items()}
            surfaces: dict[str, tuple[str, int]] = {}
            for key, count in self.lexicon["surface"].items():
                stem, _, word = key.partition("\t")
                if stem not in surfaces or count > surfaces[stem][1]:
                    surfaces[stem] = (word, count)
            return {
                "n_docs": len(self.meta),
                "df": df,
                "surface": surfaces,
                "lexicon": {
                    "word": self.lexicon["word"].most_common(40_000),
                    "phrase": [(p, c) for p, c in self.lexicon["phrase"].most_common(25_000) if c > 1],
                    "author": self.lexicon["author"].most_common(30_000),
                },
            }

    def model_sample(self, limit: int, seed: int) -> dict:
        """Phase 2: a sample of term-frequency vectors for the SVD, plus graph records."""
        with self.lock:
            ids = list(self.meta)
            if len(ids) > limit:
                ids = random.Random(seed).sample(ids, limit)
            sample = [{
                "id": d,
                "tf": self.index.term_frequencies(d),
                "titles": sorted(self.index.title_terms.get(d, ())),
                "year": self.meta[d]["year"],
                "title": self.meta[d]["title"],
            } for d in ids]
        graph = list(self.store.graph_records())
        return {"sample": sample, "graph": graph}

    def _install_model(self, model: GlobalModel, persist: bool) -> dict[str, int]:
        self.model = model
        self._vectorize_all()
        assignments = {doc_id: int(meta["cluster"]) for doc_id, meta in self.meta.items() if meta["cluster"] is not None}
        if persist:
            path = self.settings.data_dir / "model.npz"
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(model.to_bytes())
            tmp.replace(path)
            self.store.update_clusters(assignments)
            self.store.set_meta("model_version", model.version)
        self._rebuild_tries()
        return assignments

    def install_model(self, blob: bytes) -> dict:
        model = GlobalModel.from_bytes(blob)
        with self.lock:
            if self.model and model.version < self.model.version:
                return {"accepted": False, "version": self.model.version}
            assignments = self._install_model(model, persist=True)
        log.info("installed model v%d from %s (%d terms, %d concepts)", model.version, model.leader,
                 len(model.vsm), model.lsa.k if model.lsa else 0)
        return {"accepted": True, "version": model.version, "assignments": assignments}

    def _install_analytics(self, analytics: dict, persist: bool) -> None:
        graph = KnowledgeGraph.from_payload(analytics["graph"])
        metrics = graph.metrics
        rows = []
        for doc_id, meta in self.meta.items():
            m = metrics.get(doc_id)
            if m:
                meta.update(pagerank=m["pagerank"], pagerank_pct=m["pagerank_pct"], in_citations=m["in_citations"])
                rows.append((m["pagerank"], m["pagerank_pct"], m["hub"], m["authority"], m["in_citations"],
                             m["out_citations"], m["community"], doc_id))
        self.graph = graph
        self.analytics = analytics
        if persist:
            self.store.update_metrics(rows)
            path = self.settings.data_dir / "analytics.json.gz"
            tmp = path.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(analytics, fh)
            tmp.replace(path)

    def install_analytics(self, blob: bytes) -> dict:
        analytics = json.loads(zlib.decompress(blob))
        with self.lock:
            current = (self.analytics or {}).get("version", 0)
            if analytics.get("version", 0) < current:
                return {"accepted": False}
            self._install_analytics(analytics, persist=True)
        return {"accepted": True}

    # ================================================================== query evaluation

    def _resolver(self) -> Resolver:
        def term(text: str) -> set[str]:
            terms = analyze(text)
            if not terms:
                return self.index.all_docs()  # stop words match everything
            if len(terms) > 1:  # "state-of-the-art" analyses to several terms: treat as a phrase
                return self.index.phrase_docs(terms)
            return self.index.docs(terms[0])

        def phrase(text: str) -> set[str]:
            terms = analyze(text)
            return self.index.phrase_docs(terms) if terms else self.index.all_docs()

        return Resolver(term=term, phrase=phrase, field=self._field_docs, universe=self.index.all_docs)

    def _field_docs(self, name: str, value: str) -> set[str]:
        value = value.strip()
        if name == "author":
            tokens = [t for t in author_key(value).split() if len(t) > 1]
            if not tokens:
                return set()
            exact = self.author_names.get(author_key(value))
            if exact:
                return set(exact)
            sets = [self.author_tokens.get(t, set()) for t in tokens]
            return set.intersection(*map(set, sets)) if sets else set()
        if name == "year":
            low, high = year_bounds(value)
            return {d for d, m in self.meta.items() if m["year"] and (low is None or m["year"] >= low)
                    and (high is None or m["year"] <= high)}
        if name == "title":
            terms = analyze(value)
            if not terms:
                return set()
            if len(terms) > 1:
                return {d for d in self.index.phrase_docs(terms) if terms[0] in self.index.title_terms.get(d, ())}
            return self.index.title_docs(terms[0])
        if name == "topic":
            wanted = self._topic_ids(value)
            return {d for d, m in self.meta.items() if m["cluster"] in wanted}
        if name == "venue":
            needle = fold(value)
            return {d for d, m in self.meta.items() if m["venue"] and needle in fold(m["venue"])}
        if name == "source":
            return {d for d, m in self.meta.items() if (m["source"] or "").lower() == value.lower()}
        if name == "doi":
            needle = value.lower().removeprefix("https://doi.org/")
            return {d for d, m in self.meta.items() if (m["doi"] or "").lower() == needle}
        return set()

    def _topic_ids(self, value: str) -> set[int]:
        if value.lstrip("-").isdigit():
            return {int(value)}
        needle = fold(value)
        topics = self.model.topics if self.model else []
        return {t["id"] for t in topics if needle in fold(t["label"])}

    def _filter_set(self, filters: dict) -> set[str] | None:
        """Facet filters from the UI (year range, topic, author, source)."""
        if not filters:
            return None
        year_from, year_to = filters.get("year_from"), filters.get("year_to")
        topics = set(filters.get("topics") or [])
        author = filters.get("author")
        source = filters.get("source")
        if not any([year_from, year_to, topics, author, source]):
            return None
        author_docs = self._field_docs("author", author) if author else None
        out = set()
        for doc_id, m in self.meta.items():
            year = m["year"]
            if year_from and (not year or year < year_from):
                continue
            if year_to and (not year or year > year_to):
                continue
            if topics and m["cluster"] not in topics:
                continue
            if source and m["source"] != source:
                continue
            if author_docs is not None and doc_id not in author_docs:
                continue
            out.add(doc_id)
        return out

    @staticmethod
    def _intersect(base: set[str] | None, other: set[str] | None) -> set[str] | None:
        if other is None:
            return base
        if base is None:
            return set(other)
        return base & other

    def _query_terms(self, parsed: ParsedQuery) -> tuple[list[str], list[list[str]]]:
        stems, phrases = [], []
        for leaf in parsed.positive_terms():
            terms = analyze(leaf.text)
            stems.extend(terms)
            if isinstance(leaf, Phrase) or len(terms) > 1:
                phrases.append(terms)
        return stems, phrases

    def _keyword_scores(self, stems: list[str], candidates: set[str], phrases: list[list[str]]) -> dict[str, float]:
        if not stems or not candidates:
            return {}
        if self.model is not None and self.vectors.tfidf is not None:
            query = self.model.vsm.query_vector(stems)
            if query.nnz == 0:
                return {}
            column = np.asarray((self.vectors.tfidf @ query.T).todense()).ravel()
            scores = {}
            for doc_id in candidates:
                row = self.vectors.row.get(doc_id)
                if row is not None and column[row] > 0:
                    scores[doc_id] = float(column[row])
            # Documents folded in after the model can still match unknown words.
            missing = [d for d in candidates if d not in self.vectors.row]
            if missing:
                scores.update(self.index.tfidf_scores(stems, self.index.local_idf, set(missing)))
        else:
            scores = self.index.tfidf_scores(stems, self.index.local_idf, candidates)
        for terms in phrases:  # exact phrase matches get a boost
            for doc_id in self.index.phrase_docs(terms) & scores.keys():
                scores[doc_id] *= 1.3
        return scores

    def _query_concepts(self, stems: list[str]) -> np.ndarray | None:
        if not stems or self.model is None or self.model.lsa is None:
            return None
        query = self.model.vsm.query_vector(stems)
        if query.nnz == 0:
            return None
        vector = self.model.lsa.transform(query)[0]
        return vector if np.any(vector) else None

    def _semantic_scores(self, vector: np.ndarray | None, candidates: set[str] | None,
                         floor: float = SEMANTIC_FLOOR) -> dict[str, float]:
        if vector is None or self.vectors.concepts is None:
            return {}
        sims = self.vectors.concepts @ vector
        ids = self.vectors.ids
        if candidates is None:
            hits = np.nonzero(sims >= floor)[0]
            return {ids[i]: float(sims[i]) for i in hits if ids[i] in self.meta}
        return {d: float(sims[self.vectors.row[d]]) for d in candidates
                if d in self.vectors.row and sims[self.vectors.row[d]] >= floor}

    def _sort_value(self, doc_id: str, sort: str) -> float:
        m = self.meta[doc_id]
        if sort == "year_desc":
            return float(m["year"] or 0)
        if sort == "year_asc":
            return -float(m["year"] or 9999)
        if sort == "citations":
            return float(m["in_citations"] or 0) * 1e6 + float(m["cited_by_count"] or 0)
        return float(m["pagerank"] or 0)

    def _top(self, scores: dict[str, float], k: int) -> list[list]:
        return [[d, round(s, 6)] for d, s in sorted(scores.items(), key=lambda item: -item[1])[:k]]

    def search(self, payload: dict) -> dict:
        """Evaluate a query on this shard and return ranked lists plus cards and facets."""
        query = payload.get("query", "")
        mode = payload.get("mode", "hybrid")
        k = max(1, min(int(payload.get("k", 10)), 500))
        sort = payload.get("sort", "relevance")
        parsed = parse_query(query, strict=(mode == "boolean"))
        with self.lock:
            filters = self._filter_set(payload.get("filters") or {})
            resolver = self._resolver()
            stems, phrases = self._query_terms(parsed)

            constraint = parsed.constraint()
            allowed = None if constraint is ALL else (set() if constraint is EMPTY else evaluate(constraint, resolver).docs)
            allowed = self._intersect(allowed, filters)

            keyword_scores: dict[str, float] = {}
            semantic_scores: dict[str, float] = {}
            if mode == "boolean":
                matches = evaluate(parsed.ast, resolver).docs
                matches = matches if filters is None else matches & filters
                keyword_scores = self._keyword_scores(stems, matches, phrases)
                for doc_id in matches:  # documents matched only through filters/negations still rank
                    keyword_scores.setdefault(doc_id, 1e-6 * (1 + self.meta[doc_id]["pagerank"] * 1e3))
            else:
                if mode in ("keyword", "hybrid"):
                    candidates: set[str] = set()
                    for leaf in parsed.positive_terms():
                        candidates |= resolver.phrase(leaf.text) if isinstance(leaf, Phrase) else resolver.term(leaf.text)
                    if not parsed.positive_terms():
                        candidates = allowed if allowed is not None else self.index.all_docs()
                    elif allowed is not None:
                        candidates &= allowed
                    keyword_scores = self._keyword_scores(stems, candidates, phrases)
                    if not stems:
                        keyword_scores = {d: 1e-6 * (1 + self.meta[d]["pagerank"] * 1e3) for d in candidates}
                if mode in ("semantic", "hybrid"):
                    semantic_scores = self._semantic_scores(self._query_concepts(stems), allowed)

            union = keyword_scores.keys() | semantic_scores.keys()
            if sort != "relevance":
                ordered = {d: self._sort_value(d, sort) for d in union}
                lists = {"sorted": self._top(ordered, k)}
            else:
                lists = {"keyword": self._top(keyword_scores, k), "semantic": self._top(semantic_scores, k)}

            facets = self._facets(union) if payload.get("facets", True) else {}
            wanted = {d for items in lists.values() for d, _ in items}
            highlight = set(stems)
            vector = self._query_concepts(stems) if mode in ("semantic", "hybrid") else None
            if vector is not None and self.model is not None and self.model.lsa is not None:
                highlight |= {self.model.vsm.terms[i] for i, _ in self.model.lsa.top_terms(vector, 8)}
            cards = self.cards(wanted, highlight, keyword_scores, semantic_scores)

        return {
            **lists,
            "total_keyword": len(keyword_scores),
            "total_semantic": len(semantic_scores),
            "total": len(union),
            "docs": cards,
            "facets": facets,
            "model_version": self.model.version if self.model else None,
        }

    def _facets(self, ids) -> dict:
        years, topics, authors, sources = Counter(), Counter(), Counter(), Counter()
        for doc_id in ids:
            m = self.meta.get(doc_id)
            if not m:
                continue
            if m["year"]:
                years[m["year"]] += 1
            if m["cluster"] is not None:
                topics[m["cluster"]] += 1
            authors.update(m["authors"][:6])
            if m["source"]:
                sources[m["source"]] += 1
        # String keys: the local node is called in-process, peers through JSON, and the
        # merged facets must not count 1991 and "1991" as different years.
        return {"years": {str(k): v for k, v in years.items()}, "topics": {str(k): v for k, v in topics.items()},
                "authors": dict(authors.most_common(25)), "sources": dict(sources)}

    def cards(self, ids, highlight: set[str] | None = None, keyword: dict | None = None,
              semantic: dict | None = None) -> dict[str, dict]:
        ids = [d for d in ids if d in self.meta]
        if not ids:
            return {}
        summaries = self.store.summaries(ids)
        texts = self.store.texts(ids) if highlight is not None else {}
        cards = {}
        for doc_id in ids:
            row = summaries.get(doc_id)
            if row is None:
                continue
            card = {key: row.get(key) for key in CARD_FIELDS}
            card["cluster"] = self.meta[doc_id]["cluster"]
            card["node"] = self.node_id
            if highlight is not None:
                title, abstract, body = texts.get(doc_id, ("", "", ""))
                card["snippet"] = make_snippet(abstract or body or title, highlight)
            if keyword is not None or semantic is not None:
                card["scores"] = {"keyword": (keyword or {}).get(doc_id), "semantic": (semantic or {}).get(doc_id)}
            cards[doc_id] = card
        return cards

    def explain(self, query: str) -> dict:
        parsed = parse_query(query, strict=True)
        with self.lock:
            trace = evaluate(parsed.ast, self._resolver(), trace=True)
        return {"steps": [vars(step) for step in trace.steps], "matches": len(trace.docs)}

    def vector_search(self, vector: list[float], k: int, exclude: list[str]) -> dict:
        with self.lock:
            if self.vectors.concepts is None or not vector:
                return {"results": [], "docs": {}}
            sims = self.vectors.concepts @ np.asarray(vector, dtype=np.float32)
            skip = set(exclude)
            order = np.argsort(-sims)
            results = []
            for i in order:
                doc_id = self.vectors.ids[i]
                if doc_id in skip or doc_id not in self.meta:
                    continue
                results.append([doc_id, round(float(sims[i]), 6)])
                if len(results) >= k:
                    break
            return {"results": results, "docs": self.cards([d for d, _ in results])}

    # ================================================================== reads

    def document(self, doc_id: str) -> dict | None:
        doc = self.store.document(doc_id)
        if doc is None:
            return None
        with self.lock:
            meta = self.meta.get(doc_id, {})
            doc["cluster"] = meta.get("cluster")
            vector = self.doc_vector(doc_id)
            doc["vector"] = vector.tolist() if vector is not None else None
            if self.model and self.model.lsa is not None and vector is not None:
                doc["concepts"] = [{"term": self.model.display(self.model.vsm.terms[i]), "weight": round(w, 4)}
                                   for i, w in self.model.lsa.top_terms(vector, 12)]
            tf = self.index.term_frequencies(doc_id)
            if self.model:
                weighted = sorted(((t, (1 + np.log(c)) * self.model.vsm.idf_of(t)) for t, c in tf.items()),
                                  key=lambda item: -item[1])[:15]
                doc["top_terms"] = [{"term": self.model.display(t), "weight": round(float(w), 3)} for t, w in weighted if w > 0]
        doc["node"] = self.node_id
        return doc

    def points(self, limit: int, seed: int = 11) -> list[dict]:
        with self.lock:
            if self.vectors.coords is None:
                return []
            rows = list(range(len(self.vectors.ids)))
            if len(rows) > limit:
                rows = random.Random(seed).sample(rows, limit)
            out = []
            for i in rows:
                doc_id = self.vectors.ids[i]
                meta = self.meta.get(doc_id)
                if meta is None:
                    continue
                x, y, z = (float(v) for v in self.vectors.coords[i][:3])
                out.append({"id": doc_id, "title": meta["title"][:140], "year": meta["year"],
                            "cluster": meta["cluster"], "x": round(x, 4), "y": round(y, 4), "z": round(z, 4)})
            return out

    def stats(self) -> dict:
        with self.lock:
            postings = sum(len(docs) for docs in self.index.postings.values())
            return {
                "node_id": self.node_id,
                "documents": len(self.meta),
                "terms": len(self.index.postings),
                "postings": postings,
                "authors": len(self.author_names),
                "avg_length": round(self.index.average_length, 1),
                "db_bytes": self.store.size_bytes(),
                "model_version": self.model.version if self.model else None,
                "analytics_version": (self.analytics or {}).get("version"),
                "trie_nodes": self.words.node_count + self.phrases.node_count + self.authors.node_count,
                "loaded_in_ms": round(self.loaded_in_ms, 1),
            }

    def info(self) -> dict:
        """Small summary answered on every PING."""
        return {"documents": len(self.meta), "model_version": self.model.version if self.model else None}
