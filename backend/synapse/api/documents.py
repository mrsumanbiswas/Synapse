"""Document details, similar documents, connection graphs, BibTeX, authors."""

from __future__ import annotations

import re
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ..graph.knowledge_graph import author_key
from ..p2p.cluster import PeerError
from .deps import Admin, NodeDep, OptionalUser

router = APIRouter(tags=["documents"])


def _fetch(node, doc_id: str) -> dict:
    owner = doc_id.split(":", 1)[0]
    try:
        payload, _ = node.cluster.call(owner, "GET_DOC", {"id": doc_id}, timeout=10)
    except PeerError as exc:
        raise HTTPException(503, f"The shard holding this document ({owner}) is offline: {exc}") from exc
    doc = payload.get("doc")
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


def _light(node, doc_id: str) -> dict:
    graph = node.engine.graph
    doc = graph.docs.get(doc_id, {}) if graph else {}
    metrics = graph.metrics.get(doc_id, {}) if graph else {}
    return {"id": doc_id, "title": doc.get("title", doc_id), "year": doc.get("year"),
            "authors": doc.get("authors", [])[:4], "citations": metrics.get("in_citations", 0),
            "pagerank": metrics.get("pagerank", 0.0)}


@router.get("/documents/{doc_id}")
def document(doc_id: str, node: NodeDep, user: OptionalUser):
    doc = _fetch(node, doc_id)
    doc.pop("vector", None)
    graph = node.engine.graph
    model = node.engine.model
    topic = model.topic(doc.get("cluster")) if model else None
    doc["topic"] = {"id": topic["id"], "label": topic["label"], "terms": topic.get("terms", [])[:8]} if topic else None

    keys = (node.engine.analytics or {}).get("keys", {})
    approximate = (node.engine.analytics or {}).get("approximate_references", {}).get(doc_id, {})
    cited, citing = [], []
    if graph and doc_id in graph.citations:
        cited = sorted((_light(node, d) for d in graph.citations.successors(doc_id)), key=lambda d: -d["pagerank"])
        citing = sorted((_light(node, d) for d in graph.citations.predecessors(doc_id)), key=lambda d: -d["pagerank"])
        doc["metrics"] = graph.metrics.get(doc_id, {})
    resolved_ids = {d["id"] for d in cited}
    for ref in doc.get("references", []):
        target = next((keys[k] for k in ref.get("keys", []) if k in keys), None) or approximate.get(str(ref["position"]))
        ref["resolved"] = target
        ref["resolved_title"] = graph.docs.get(target, {}).get("title") if graph and target else None
        if target:
            resolved_ids.add(target)
    doc["references_in_corpus"] = cited
    doc["cited_by"] = citing
    doc["references_total"] = len(doc.get("references", []))
    doc["bookmarked"] = bool(user) and doc_id in node.app.bookmarked_ids(user["id"])
    return doc


@router.get("/documents/{doc_id}/similar")
def similar(doc_id: str, node: NodeDep, k: Annotated[int, Query(ge=1, le=30)] = 8):
    """Nearest neighbours in LSA concept space, gathered from every shard."""
    doc = _fetch(node, doc_id)
    return {"id": doc_id, "results": node.search.similar(doc_id, doc.get("vector"), k)}


@router.get("/documents/{doc_id}/graph")
def connection_graph(doc_id: str, node: NodeDep, depth: Annotated[int, Query(ge=1, le=2)] = 1,
                     authors: bool = True, similar: bool = True,
                     limit: Annotated[int, Query(ge=5, le=80)] = 24):
    """Citations in and out, authors, and semantically similar papers around one document."""
    graph = node.engine.graph
    fetched: dict[str, dict] = {}

    def get_doc() -> dict:
        if "doc" not in fetched:
            fetched["doc"] = _fetch(node, doc_id)
        return fetched["doc"]

    result = graph.neighborhood(doc_id, depth=depth, per_side=limit, include_authors=authors) if graph else None
    if not result or not result["nodes"]:
        doc = get_doc()
        result = {"nodes": [{"id": doc_id, "type": "paper", "role": "focus", "label": doc["title"],
                             "year": doc.get("year"), "cluster": doc.get("cluster"), "depth": 0}], "links": []}
        if authors:
            for name in doc.get("authors", [])[:12]:
                result["nodes"].append({"id": f"author:{author_key(name)}", "type": "author", "role": "author",
                                        "label": name, "depth": 1})
                result["links"].append({"source": f"author:{author_key(name)}", "target": doc_id, "type": "wrote"})
    if similar:
        vector = get_doc().get("vector")
        present = {n["id"] for n in result["nodes"]}
        for hit in node.search.similar(doc_id, vector, 6):
            if hit["id"] not in present:
                result["nodes"].append({"id": hit["id"], "type": "paper", "role": "similar", "label": hit["title"],
                                        "year": hit.get("year"), "cluster": hit.get("cluster"),
                                        "similarity": hit.get("score"), "depth": 1})
            result["links"].append({"source": doc_id, "target": hit["id"], "type": "similar",
                                    "weight": hit.get("score")})
    return result


def _bibtex_key(doc: dict) -> str:
    last = re.sub(r"[^a-z]", "", (doc.get("authors") or ["anon"])[0].split()[-1].lower()) or "anon"
    first_word = next((w for w in re.findall(r"[a-z]+", doc.get("title", "").lower()) if len(w) > 3), "paper")
    return f"{last}{doc.get('year') or ''}{first_word}"


@router.get("/documents/{doc_id}/bibtex", response_class=PlainTextResponse)
def bibtex(doc_id: str, node: NodeDep):
    doc = _fetch(node, doc_id)

    def esc(value) -> str:
        return str(value).replace("{", "\\{").replace("}", "\\}")

    fields = [("title", doc.get("title")), ("author", " and ".join(doc.get("authors") or [])),
              ("year", doc.get("year")), ("journal", doc.get("venue")), ("doi", doc.get("doi")),
              ("url", doc.get("url"))]
    body = ",\n".join(f"  {name} = {{{esc(value)}}}" for name, value in fields if value)
    return f"@article{{{_bibtex_key(doc)},\n{body}\n}}\n"


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, node: NodeDep, user: Admin):
    owner = doc_id.split(":", 1)[0]
    try:
        payload, _ = node.cluster.call(owner, "DELETE_DOC", {"id": doc_id})
    except PeerError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not payload.get("deleted"):
        raise HTTPException(404, "Document not found")
    node.coordinator.rebuild_in_background(f"document deleted by {user['email']}")
    return {"deleted": doc_id}


@router.get("/recent")
def recent(node: NodeDep, limit: Annotated[int, Query(ge=1, le=30)] = 8):
    return {"documents": node.recent_documents(limit)}


@router.get("/authors/{name}")
def author(name: str, node: NodeDep):
    graph = node.engine.graph
    profile = graph.author(name) if graph else None
    display = profile["name"] if profile else name
    papers = node.search.search(f'author:"{display}"', mode="boolean", size=50, sort="year_desc")["results"]
    if not profile and not papers:
        raise HTTPException(404, "Author not found")

    network = {"nodes": [], "links": []}
    if profile and graph:
        key = profile["key"]
        neighbours = sorted(graph.coauthors[key].items(), key=lambda item: -item[1].get("weight", 1))[:18]
        members = [key] + [k for k, _ in neighbours]
        for member in members:
            metrics = graph.author_metrics.get(member, {})
            network["nodes"].append({"id": f"author:{member}", "type": "author", "label": metrics.get("name", member),
                                     "papers": metrics.get("papers", 0), "role": "focus" if member == key else "coauthor"})
        for a, b, data in graph.coauthors.subgraph(members).edges(data=True):
            network["links"].append({"source": f"author:{a}", "target": f"author:{b}", "weight": data.get("weight", 1)})

    topics = Counter(p["topic"]["label"] for p in papers if p.get("topic"))
    years = Counter(p["year"] for p in papers if p.get("year"))
    return {
        "name": display,
        "metrics": {k: v for k, v in (profile or {}).items() if k not in ("doc_ids", "coauthor_list", "key")},
        "coauthors": (profile or {}).get("coauthor_list", []),
        "papers": papers,
        "topics": [{"label": label, "count": count} for label, count in topics.most_common()],
        "years": sorted([year, count] for year, count in years.items()),
        "network": network,
    }
