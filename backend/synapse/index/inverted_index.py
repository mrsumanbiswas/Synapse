"""Positional inverted index built from plain dicts and sets.

    postings["network"] = {"node-a:91f2...": array('I', [3, 17, 40]), ...}

Term -> documents lookups are dict hits, boolean logic is set algebra, and the
stored positions answer exact phrase queries such as ``"neural network"``.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Callable, Iterable, Sequence

FIELD_GAP = 8  # position gap between title and body so phrases never span fields


class InvertedIndex:
    def __init__(self) -> None:
        self.postings: dict[str, dict[str, array]] = {}
        self.doc_lengths: dict[str, int] = {}
        self.title_terms: dict[str, frozenset[str]] = {}
        self._doc_terms: dict[str, tuple[str, ...]] = {}
        self._total_length = 0

    # ------------------------------------------------------------------ building

    def add(self, doc_id: str, title_terms: Sequence[str], body_terms: Sequence[str]) -> None:
        """Index a document; title positions come first, then the body after a gap."""
        if doc_id in self.doc_lengths:
            self.remove(doc_id)
        positions: dict[str, array] = {}
        for pos, term in enumerate(title_terms):
            positions.setdefault(term, array("I")).append(pos)
        offset = len(title_terms) + FIELD_GAP
        for pos, term in enumerate(body_terms):
            positions.setdefault(term, array("I")).append(offset + pos)
        self.add_positions(doc_id, positions, len(title_terms) + len(body_terms), title_terms)

    def add_positions(self, doc_id: str, positions: dict[str, array], length: int,
                      title_terms: Iterable[str] = ()) -> None:
        """Insert precomputed postings (used when loading the index from SQLite)."""
        for term, plist in positions.items():
            self.postings.setdefault(term, {})[doc_id] = plist
        self.doc_lengths[doc_id] = length
        self.title_terms[doc_id] = frozenset(title_terms)
        self._doc_terms[doc_id] = tuple(positions)
        self._total_length += length

    def remove(self, doc_id: str) -> None:
        for term in self._doc_terms.pop(doc_id, ()):
            docs = self.postings.get(term)
            if docs is not None:
                docs.pop(doc_id, None)
                if not docs:
                    del self.postings[term]
        self._total_length -= self.doc_lengths.pop(doc_id, 0)
        self.title_terms.pop(doc_id, None)

    # ------------------------------------------------------------------ lookups

    def __contains__(self, doc_id: str) -> bool:
        return doc_id in self.doc_lengths

    def __len__(self) -> int:
        return len(self.doc_lengths)

    @property
    def average_length(self) -> float:
        return self._total_length / len(self.doc_lengths) if self.doc_lengths else 0.0

    def all_docs(self) -> set[str]:
        return set(self.doc_lengths)

    def docs(self, term: str) -> set[str]:
        return set(self.postings.get(term, ()))

    def df(self, term: str) -> int:
        return len(self.postings.get(term, ()))

    def tf(self, term: str, doc_id: str) -> int:
        plist = self.postings.get(term, {}).get(doc_id)
        return len(plist) if plist is not None else 0

    def terms_of(self, doc_id: str) -> tuple[str, ...]:
        return self._doc_terms.get(doc_id, ())

    def term_frequencies(self, doc_id: str) -> dict[str, int]:
        return {term: len(self.postings[term][doc_id]) for term in self._doc_terms.get(doc_id, ())}

    def positions(self, term: str, doc_id: str) -> array | None:
        return self.postings.get(term, {}).get(doc_id)

    def vocabulary(self) -> Iterable[str]:
        return self.postings.keys()

    def title_docs(self, term: str) -> set[str]:
        return {d for d in self.postings.get(term, ()) if term in self.title_terms.get(d, ())}

    def phrase_docs(self, terms: Sequence[str]) -> set[str]:
        """Documents containing ``terms`` at consecutive positions."""
        if not terms:
            return set()
        lists = [self.postings.get(t) for t in terms]
        if any(plist is None for plist in lists):
            return set()
        if len(terms) == 1:
            return set(lists[0])
        # Intersect starting from the rarest term, then verify positions.
        candidates = set(min(lists, key=len))
        for plist in lists:
            candidates &= plist.keys()
        matches = set()
        for doc in candidates:
            following = [set(lists[i][doc]) for i in range(1, len(terms))]
            for start in lists[0][doc]:
                if all(start + i in following[i - 1] for i in range(1, len(terms))):
                    matches.add(doc)
                    break
        return matches

    # ------------------------------------------------------------------ scoring

    def tfidf_scores(self, query_terms: Sequence[str], idf: Callable[[str], float],
                     candidates: set[str] | None = None, title_boost: float = 1.5) -> dict[str, float]:
        """Cosine-style TF-IDF scores with term-at-a-time accumulators.

        Used before a global vector model exists; afterwards the sparse-matrix
        version in :mod:`synapse.vector.vsm` takes over.
        """
        scores: dict[str, float] = {}
        weights = {t: idf(t) for t in set(query_terms)}
        for term, weight in weights.items():
            for doc, plist in self.postings.get(term, {}).items():
                if candidates is not None and doc not in candidates:
                    continue
                w = (1 + math.log(len(plist))) * weight
                if term in self.title_terms.get(doc, ()):
                    w *= title_boost
                scores[doc] = scores.get(doc, 0.0) + w * weight
        for doc in scores:
            scores[doc] /= math.sqrt(self.doc_lengths.get(doc) or 1)
        return scores

    def local_idf(self, term: str) -> float:
        df = self.df(term)
        return math.log((1 + len(self.doc_lengths)) / (1 + df)) + 1 if df else 0.0
