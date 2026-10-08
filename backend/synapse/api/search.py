"""Search, autocomplete, model comparison and query explanation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..services.search import MODES, SORTS
from .deps import NodeDep, OptionalUser

router = APIRouter(tags=["search"])


@router.get("/search")
def search(
    node: NodeDep,
    user: OptionalUser,
    q: Annotated[str, Query(max_length=500)] = "",
    mode: Annotated[str, Query(pattern="|".join(MODES))] = "hybrid",
    page: Annotated[int, Query(ge=1, le=50)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 10,
    sort: Annotated[str, Query(pattern="|".join(SORTS))] = "relevance",
    year_from: int | None = None,
    year_to: int | None = None,
    topic: Annotated[list[int] | None, Query()] = None,
    author: str | None = None,
    source: str | None = None,
    log: bool = True,
):
    """Distributed search across every node. ``q='*'`` lists everything."""
    filters = {"year_from": year_from, "year_to": year_to, "topics": topic or [], "author": author, "source": source}
    result = node.search.search(q or "*", mode=mode, page=page, size=size, sort=sort, filters=filters)
    if user:
        bookmarked = node.app.bookmarked_ids(user["id"])
        for hit in result["results"]:
            hit["bookmarked"] = hit["id"] in bookmarked
    if log and q.strip() and q.strip() != "*" and page == 1:
        node.app.log_search(user["id"] if user else None, q, mode, result["total"], result["took_ms"])
    return result


@router.get("/autocomplete")
def autocomplete(node: NodeDep, q: Annotated[str, Query(max_length=200)] = "",
                 limit: Annotated[int, Query(ge=1, le=20)] = 8):
    """Trie-backed suggestions: phrases, words, authors, past searches and typo fixes."""
    suggestions = node.engine.autocomplete(q, limit)
    prefix = q.strip().lower()
    if prefix:
        seen = {s["text"].lower() for s in suggestions}
        for item in node.app.popular_queries(limit=30):
            if item["query"].startswith(prefix) and item["query"] != prefix and item["query"] not in seen:
                suggestions.insert(0, {"text": item["query"], "kind": "history", "count": item["count"]})
                seen.add(item["query"])
    return {"query": q, "suggestions": suggestions[:limit]}


@router.get("/search/compare")
def compare(node: NodeDep, q: Annotated[str, Query(min_length=1, max_length=500)],
            size: Annotated[int, Query(ge=1, le=30)] = 10):
    """TF-IDF (keyword) and LSA (semantic) rankings of the same query, side by side."""
    return node.search.compare(q, size)


@router.get("/search/explain")
def explain(node: NodeDep, q: Annotated[str, Query(min_length=1, max_length=500)]):
    """How the stack-based parser reads a query, with document counts per stack step."""
    return node.search.explain(q)


@router.get("/search/concepts")
def concepts(node: NodeDep, q: Annotated[str, Query(min_length=1, max_length=500)]):
    return {"query": q, "concepts": node.search.concepts(q, 15)}
