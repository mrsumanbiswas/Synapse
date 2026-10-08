from collections import Counter

import numpy as np

from synapse.graph.knowledge_graph import KnowledgeGraph, h_index
from synapse.graph.temporal import kleinberg_bursts
from synapse.text.tokenizer import analyze
from synapse.vector.clustering import kmeans
from synapse.vector.lsa import LatentSemanticModel
from synapse.vector.vsm import VectorSpaceModel, cosine

CORPUS = [
    "car engine road driving vehicle",
    "car road traffic vehicle speed",
    "automobile engine road vehicle driving",
    "automobile traffic road vehicle",
    "protein gene cell biology dna",
    "gene expression cell protein",
    "dna sequencing gene cell",
    "stock market price trading finance",
    "market finance investment price",
]


def _fit():
    tfs = [Counter(analyze(text)) for text in CORPUS]
    df = Counter(term for tf in tfs for term in tf)
    vsm = VectorSpaceModel.from_document_frequencies(df, len(tfs))
    matrix = vsm.vectorize(tfs)
    return vsm, matrix, LatentSemanticModel.fit(matrix, 3)


def test_cosine_formula():
    assert cosine(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == 1.0
    assert cosine(np.array([1.0, 0.0]), np.array([0.0, 2.0])) == 0.0


def test_lsa_finds_synonyms_tfidf_cannot():
    vsm, matrix, lsa = _fit()
    query = vsm.query_vector(analyze("car"))
    keyword = (matrix @ query.T).toarray().ravel()
    semantic = lsa.transform(matrix) @ lsa.transform(query)[0]
    automobile_docs = [2, 3]
    assert all(keyword[i] == 0 for i in automobile_docs)  # no shared word
    assert all(semantic[i] > 0.8 for i in automobile_docs)  # same concept
    assert all(semantic[i] < 0.3 for i in (4, 5, 6, 7, 8))


def test_kmeans_separates_topics():
    _, matrix, lsa = _fit()
    _, labels = kmeans(lsa.transform(matrix), 3)
    assert len(set(labels[:4])) == 1 and len(set(labels[4:7])) == 1 and len(set(labels[7:])) == 1
    assert len({labels[0], labels[4], labels[7]}) == 3


def test_kleinberg_detects_injected_burst():
    totals = [100] * 20
    counts = [2] * 20
    counts[12:15] = [30, 35, 28]
    bursts = kleinberg_bursts(counts, totals)
    assert [(start, end) for start, end, _ in bursts] == [(12, 14)]


def test_knowledge_graph_metrics():
    docs = [{"id": d, "title": d, "year": 2000 + i, "authors": a} for i, (d, a) in
            enumerate([("a", ["X", "Y"]), ("b", ["Y"]), ("c", ["Z"]), ("d", ["X", "Z"])])]
    graph = KnowledgeGraph.build(docs, [("b", "a"), ("c", "a"), ("d", "a"), ("d", "b")])
    assert max(graph.metrics, key=lambda d: graph.metrics[d]["pagerank"]) == "a"
    assert graph.metrics["a"]["in_citations"] == 3
    assert graph.shortest_path("c", "b") in (["c", "a", "b"], ["c", "d", "b"])
    assert graph.author("x")["papers"] == 2
    assert h_index([10, 4, 3, 1]) == 3
