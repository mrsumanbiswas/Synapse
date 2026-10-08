"""Shard-side analysis of one record: regex extraction, tokenisation, identity keys.

This is the CPU work that the ingesting node *delegates* to the shard that owns
a document: raw records travel over the socket, the owner parses them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..text import extract
from ..text.tokenizer import analyze, analyze_pairs, phrases, surface_words
from .records import RawRecord

MAX_INDEX_CHARS = 60_000
MAX_REFERENCES = 400


@dataclass
class AnalyzedDocument:
    id: str
    content_hash: str
    record: RawRecord
    title_terms: list[str]
    body_terms: list[str]
    words: Counter = field(default_factory=Counter)
    phrases: Counter = field(default_factory=Counter)
    surfaces: Counter = field(default_factory=Counter)  # (stem, surface word) -> count
    entities: list[tuple[str, str, int]] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    identity_keys: list[str] = field(default_factory=list)

    @property
    def length(self) -> int:
        return len(self.title_terms) + len(self.body_terms)


def reference_keys(ref: dict) -> list[str]:
    keys = []
    if ref.get("key"):
        keys.append(ref["key"])
    doi = extract.normalize_doi(ref.get("doi"))
    if doi:
        keys.append(f"doi:{doi}")
    raw = ref.get("raw") or ""
    title = ref.get("title") or (extract.guess_reference_title(raw) if raw else None)
    if title:
        keys.append(f"title:{extract.normalize_title(title)}")
    if raw:
        keys.extend(f"doi:{d}" for d in extract.extract_dois(raw))
        keys.extend(f"arxiv:{a.split('v')[0]}" for a in extract.extract_arxiv_ids(raw))
    return list(dict.fromkeys(k for k in keys if k and not k.endswith(":")))


def analyze_record(record: RawRecord, node_id: str) -> AnalyzedDocument:
    content_hash = record.content_hash()
    text = "\n".join(part for part in (record.abstract, record.body[:MAX_INDEX_CHARS]) if part)
    own_doi = extract.normalize_doi(record.doi)

    entities: list[tuple[str, str, int]] = []
    entities += [("email", e, 1) for e in extract.extract_emails(text)]
    entities += [("url", u, 1) for u in extract.extract_urls(text)][:50]
    entities += [("doi", d, 1) for d in extract.extract_dois(text) if d != own_doi][:50]
    entities += [("arxiv", a, 1) for a in extract.extract_arxiv_ids(text)][:50]
    entities += [("citation", f"[{n}]", c) for n, c in extract.extract_citation_markers(text).items()]
    entities += [("author_year", c, 1) for c in extract.extract_author_year_citations(text)][:50]
    entities += [("keyword", k.lower(), 1) for k in record.keywords[:30] if k]
    entities += [("category", c, 1) for c in record.categories[:10] if c]

    references = []
    for position, ref in enumerate(record.references[:MAX_REFERENCES]):
        keys = reference_keys(ref)
        if not keys and not ref.get("raw"):
            continue
        references.append({
            "position": position,
            "raw": ref.get("raw"),
            "title": ref.get("title") or (extract.guess_reference_title(ref["raw"]) if ref.get("raw") else None),
            "year": ref.get("year"),
            "keys": keys,
        })

    identity = record.identity_keys()
    if record.external_id and record.external_id.startswith("arxiv:"):
        identity.append(f"arxiv:{record.external_id.split(':', 1)[1]}")

    # URLs are kept as entities above; their fragments ("https", "github", "com") are not index terms.
    text = extract.URL_RE.sub(" ", text)
    head = f"{record.title}\n{extract.URL_RE.sub(' ', record.abstract)}"
    return AnalyzedDocument(
        id=f"{node_id}:{content_hash[:12]}",
        content_hash=content_hash,
        record=record,
        title_terms=analyze(record.title),
        body_terms=analyze(text),
        words=Counter(surface_words(f"{head}\n{record.body[:20_000]}")),
        phrases=Counter(phrases(record.title)) + Counter(phrases(record.abstract)),
        surfaces=Counter(analyze_pairs(head)),
        entities=entities,
        references=references,
        identity_keys=list(dict.fromkeys(identity)),
    )
