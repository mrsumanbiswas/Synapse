"""Latent Semantic Analysis (Deerwester et al., 1990) with a truncated SVD.

    X (documents x terms)  ≈  U_k Σ_k V_kᵀ

Each row of ``V_kᵀ`` is a *concept*: a weighted blend of terms that tend to
co-occur. A document or query is mapped into concept space by ``x · V_k``, so
"car" lands next to "automobile" when both keep company with "vehicle",
"driving" and "road", even if a document never uses the word "car".

New documents are "folded in" with the same projection, which is how every
node of the cluster vectorises its own shard against one shared model.
"""

from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import svds

from .vsm import normalize_dense


class LatentSemanticModel:
    def __init__(self, components: np.ndarray, singular_values: np.ndarray,
                 explained_variance: np.ndarray | None = None):
        self.components = np.asarray(components, dtype=np.float32)  # k x V  (= V_kᵀ)
        self.singular_values = np.asarray(singular_values, dtype=np.float32)
        self.explained_variance = (
            np.asarray(explained_variance, dtype=np.float32)
            if explained_variance is not None else np.zeros_like(self.singular_values)
        )

    @property
    def k(self) -> int:
        return int(self.components.shape[0])

    @classmethod
    def fit(cls, matrix: sparse.csr_matrix, k: int, seed: int = 7) -> "LatentSemanticModel | None":
        n_docs, n_terms = matrix.shape
        k = min(k, n_docs - 1, n_terms - 1)
        if k < 2:
            return None
        rng = np.random.default_rng(seed)
        v0 = rng.standard_normal(min(matrix.shape))  # fixed start vector -> reproducible models
        _, s, vt = svds(matrix.astype(np.float64), k=k, v0=v0, solver="arpack")
        order = np.argsort(s)[::-1]
        s, vt = s[order], vt[order]
        # SVD signs are arbitrary; make the heaviest loading of each concept positive.
        heaviest = vt[np.arange(k), np.abs(vt).argmax(axis=1)]
        vt *= np.where(heaviest < 0, -1.0, 1.0)[:, None]
        total = float(matrix.multiply(matrix).sum()) or 1.0
        return cls(vt, s, (s ** 2) / total)

    def transform(self, matrix: sparse.csr_matrix) -> np.ndarray:
        """TF-IDF rows -> unit-length concept vectors."""
        if matrix.shape[0] == 0:
            return np.zeros((0, self.k), dtype=np.float32)
        projected = matrix @ self.components.T
        return normalize_dense(np.asarray(projected))

    def concept_weights(self, vector: np.ndarray) -> np.ndarray:
        """Back-project a concept vector to a weight per vocabulary term."""
        return vector @ self.components

    def top_terms(self, vector: np.ndarray, top: int = 10) -> list[tuple[int, float]]:
        weights = self.concept_weights(vector)
        top = min(top, len(weights))
        if top <= 0:
            return []
        best = np.argpartition(-weights, top - 1)[:top]
        best = best[np.argsort(-weights[best])]
        return [(int(i), float(weights[i])) for i in best if weights[i] > 0]
