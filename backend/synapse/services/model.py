"""The global model every node shares: vocabulary + IDF, LSA concepts, topic centroids.

Raw documents are sharded, but scores are only comparable across shards if all
nodes weight terms identically, so one node (the leader of a rebuild) fits the
model on statistics gathered from every shard and broadcasts it as a compressed
``.npz`` blob. Each node then vectorises its own documents locally.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field

import numpy as np

from ..vector.lsa import LatentSemanticModel
from ..vector.vsm import VectorSpaceModel


@dataclass
class GlobalModel:
    version: int
    leader: str
    built_at: float
    n_docs: int
    vsm: VectorSpaceModel
    lsa: LatentSemanticModel | None
    centroids: np.ndarray | None
    pca_mean: np.ndarray | None
    pca_components: np.ndarray | None
    topics: list[dict] = field(default_factory=list)
    surface: dict[str, str] = field(default_factory=dict)
    lexicon: dict[str, list] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    def display(self, stem: str) -> str:
        return self.surface.get(stem, stem)

    def topic(self, topic_id: int | None) -> dict | None:
        if topic_id is None:
            return None
        for topic in self.topics:
            if topic["id"] == topic_id:
                return topic
        return None

    def info(self) -> dict:
        return {
            "version": self.version,
            "leader": self.leader,
            "built_at": self.built_at,
            "documents": self.n_docs,
            "vocabulary": len(self.vsm),
            "concepts": self.lsa.k if self.lsa else 0,
            "explained_variance": float(self.lsa.explained_variance.sum()) if self.lsa else 0.0,
            "topics": len(self.topics),
            **self.stats,
        }

    # ------------------------------------------------------------------ serialisation

    def to_bytes(self) -> bytes:
        meta = {
            "version": self.version, "leader": self.leader, "built_at": self.built_at, "n_docs": self.n_docs,
            "terms": self.vsm.terms, "topics": self.topics, "surface": self.surface, "lexicon": self.lexicon,
            "stats": self.stats,
        }
        arrays = {
            "meta": np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8),
            "idf": self.vsm.idf,
        }
        if self.lsa is not None:
            arrays.update(components=self.lsa.components, singular_values=self.lsa.singular_values,
                          explained_variance=self.lsa.explained_variance)
        if self.centroids is not None:
            arrays["centroids"] = self.centroids
        if self.pca_mean is not None:
            arrays.update(pca_mean=self.pca_mean, pca_components=self.pca_components)
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        return buffer.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "GlobalModel":
        with np.load(io.BytesIO(data), allow_pickle=False) as arrays:
            meta = json.loads(arrays["meta"].tobytes().decode())
            lsa = None
            if "components" in arrays:
                lsa = LatentSemanticModel(arrays["components"], arrays["singular_values"], arrays["explained_variance"])
            return cls(
                version=meta["version"], leader=meta["leader"], built_at=meta["built_at"], n_docs=meta["n_docs"],
                vsm=VectorSpaceModel(meta["terms"], arrays["idf"]),
                lsa=lsa,
                centroids=arrays["centroids"] if "centroids" in arrays else None,
                pca_mean=arrays["pca_mean"] if "pca_mean" in arrays else None,
                pca_components=arrays["pca_components"] if "pca_components" in arrays else None,
                topics=meta.get("topics", []), surface=meta.get("surface", {}),
                lexicon=meta.get("lexicon", {}), stats=meta.get("stats", {}),
            )
