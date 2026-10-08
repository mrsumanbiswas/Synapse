"""Vector space model: documents become TF-IDF vectors compared by cosine similarity.

    weight(t, d) = (1 + log tf(t, d)) * idf(t)        idf(t) = log((1 + N) / (1 + df(t))) + 1
    similarity(A, B) = A·B / (||A|| ||B||)

Vectors live in a ``scipy.sparse`` CSR matrix (one row per document). Rows are
L2-normalised up front, so cosine similarity is a single sparse
matrix-vector product.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np
from scipy import sparse


def normalize_rows(matrix: sparse.csr_matrix) -> sparse.csr_matrix:
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
    norms[norms == 0] = 1.0
    return sparse.csr_matrix(sparse.diags(1.0 / norms) @ matrix, dtype=np.float32)


def normalize_dense(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """similarity = A·B / (||A|| ||B||) for two dense vectors."""
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b) / denominator if denominator else 0.0


class VectorSpaceModel:
    """A fixed vocabulary with global IDF weights, shared by every node of the cluster."""

    def __init__(self, terms: Sequence[str], idf: np.ndarray, title_boost: float = 1.5):
        self.terms = list(terms)
        self.index = {term: i for i, term in enumerate(self.terms)}
        self.idf = np.asarray(idf, dtype=np.float32)
        self.title_boost = title_boost

    def __len__(self) -> int:
        return len(self.terms)

    @classmethod
    def from_document_frequencies(cls, df: dict[str, int], n_docs: int, min_df: int = 2,
                                  max_df_ratio: float = 0.5, max_terms: int = 40_000) -> "VectorSpaceModel":
        """Choose the vocabulary: drop hapax terms and terms that appear almost everywhere."""
        if n_docs < 20:
            min_df, max_df_ratio = 1, 1.0
        ceiling = max(1, int(max_df_ratio * n_docs))
        kept = [(t, f) for t, f in df.items() if min_df <= f <= ceiling]
        kept.sort(key=lambda item: (-item[1], item[0]))
        kept = sorted(kept[:max_terms])
        terms = [t for t, _ in kept]
        idf = np.array([math.log((1 + n_docs) / (1 + f)) + 1 for _, f in kept], dtype=np.float32)
        return cls(terms, idf)

    def idf_of(self, term: str) -> float:
        i = self.index.get(term)
        return float(self.idf[i]) if i is not None else 0.0

    def vectorize(self, docs_tf: Sequence[dict[str, int]],
                  title_terms: Sequence[Iterable[str]] | None = None) -> sparse.csr_matrix:
        """Term-frequency dicts -> L2-normalised TF-IDF matrix (documents x vocabulary)."""
        rows, cols, values = [], [], []
        for r, tf in enumerate(docs_tf):
            titles = set(title_terms[r]) if title_terms is not None else ()
            for term, count in tf.items():
                j = self.index.get(term)
                if j is None or count <= 0:
                    continue
                weight = (1.0 + math.log(count)) * self.idf[j]
                if term in titles:
                    weight *= self.title_boost
                rows.append(r)
                cols.append(j)
                values.append(weight)
        matrix = sparse.csr_matrix(
            (np.asarray(values, dtype=np.float32), (rows, cols)),
            shape=(len(docs_tf), len(self.terms)),
            dtype=np.float32,
        )
        return normalize_rows(matrix)

    def query_vector(self, terms: Sequence[str]) -> sparse.csr_matrix:
        tf: dict[str, int] = {}
        for term in terms:
            tf[term] = tf.get(term, 0) + 1
        return self.vectorize([tf])
