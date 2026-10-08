"""Grouping documents into topics and projecting them for plotting.

* k-means (``scipy.cluster.vq.kmeans2`` with k-means++ seeding) on unit-length
  LSA vectors, followed by a few spherical refinement steps (cosine assignment).
* PCA via ``numpy.linalg.svd`` to place documents in 2-D/3-D scatter plots.
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy.cluster.vq import kmeans2

from .vsm import normalize_dense


def kmeans(vectors: np.ndarray, n_clusters: int, seed: int = 42, refine: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Return (unit-length centroids, labels) with empty clusters removed."""
    n = len(vectors)
    if n == 0:
        return np.zeros((0, vectors.shape[1] if vectors.ndim == 2 else 0), np.float32), np.zeros(0, int)
    k = max(1, min(n_clusters, n))
    if k == 1:
        return normalize_dense(vectors.mean(axis=0, keepdims=True)), np.zeros(n, dtype=int)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "one of the clusters is empty" is handled below
        centroids, labels = kmeans2(vectors.astype(np.float64), k, iter=30, minit="++",
                                    rng=np.random.default_rng(seed))
    centroids = normalize_dense(centroids)
    for _ in range(refine):
        labels = assign(vectors, centroids)
        updated = np.zeros_like(centroids)
        for c in range(len(centroids)):
            members = vectors[labels == c]
            updated[c] = members.mean(axis=0) if len(members) else centroids[c]
        updated = normalize_dense(updated)
        if np.allclose(updated, centroids, atol=1e-5):
            break
        centroids = updated

    labels = assign(vectors, centroids)
    used = np.unique(labels)
    remap = {old: new for new, old in enumerate(used)}
    return centroids[used], np.array([remap[label] for label in labels], dtype=int)


def assign(vectors: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Nearest centroid by cosine similarity (vectors and centroids are unit length)."""
    if len(centroids) == 0 or len(vectors) == 0:
        return np.zeros(len(vectors), dtype=int)
    return np.asarray(vectors @ centroids.T).argmax(axis=1)


def pca(vectors: np.ndarray, dims: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Principal axes for plotting: returns (mean, components[dims x k])."""
    mean = vectors.mean(axis=0)
    centred = vectors - mean
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    components = vt[:dims]
    if components.shape[0] < dims:  # tiny corpora: pad with zero axes
        components = np.vstack([components, np.zeros((dims - components.shape[0], vectors.shape[1]))])
    heaviest = components[np.arange(dims), np.abs(components).argmax(axis=1)]
    components *= np.where(heaviest < 0, -1.0, 1.0)[:, None]
    return mean.astype(np.float32), components.astype(np.float32)


def project(vectors: np.ndarray, mean: np.ndarray, components: np.ndarray) -> np.ndarray:
    if len(vectors) == 0:
        return np.zeros((0, components.shape[0]), dtype=np.float32)
    return ((vectors - mean) @ components.T).astype(np.float32)
