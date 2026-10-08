"""SQLite storage for one shard: documents, authors, extracted entities, references
and the precomputed postings ("index points") the in-memory index is loaded from."""

from __future__ import annotations

import json
import time
from array import array
from collections.abc import Iterator, Sequence
from pathlib import Path

from ..ingest.analysis import AnalyzedDocument
from ..text.tokenizer import fold
from .database import Database, chunked, placeholders

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    content_hash    TEXT NOT NULL UNIQUE,
    source          TEXT,
    external_id     TEXT,
    doi             TEXT,
    title           TEXT NOT NULL,
    abstract        TEXT,
    body            TEXT,
    year            INTEGER,
    published       TEXT,
    venue           TEXT,
    url             TEXT,
    language        TEXT,
    categories      TEXT,
    cited_by_count  INTEGER,
    filename        TEXT,
    job_id          TEXT,
    length          INTEGER NOT NULL DEFAULT 0,
    ingested_at     REAL NOT NULL,
    ingested_via    TEXT,
    cluster         INTEGER,
    pagerank        REAL DEFAULT 0,
    pagerank_pct    REAL DEFAULT 0,
    hub             REAL DEFAULT 0,
    authority       REAL DEFAULT 0,
    in_citations    INTEGER DEFAULT 0,
    out_citations   INTEGER DEFAULT 0,
    community       INTEGER DEFAULT -1
);
CREATE INDEX IF NOT EXISTS idx_documents_year ON documents(year);
CREATE INDEX IF NOT EXISTS idx_documents_job ON documents(job_id);

CREATE TABLE IF NOT EXISTS authors (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    norm  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_authors_norm ON authors(norm);

CREATE TABLE IF NOT EXISTS document_authors (
    doc_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES authors(id),
    position  INTEGER NOT NULL,
    PRIMARY KEY (doc_id, author_id)
);
CREATE INDEX IF NOT EXISTS idx_document_authors_author ON document_authors(author_id);

CREATE TABLE IF NOT EXISTS entities (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kind   TEXT NOT NULL,
    value  TEXT NOT NULL,
    count  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (doc_id, kind, value)
);

CREATE TABLE IF NOT EXISTS doc_references (
    doc_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    raw      TEXT,
    title    TEXT,
    year     INTEGER,
    keys     TEXT NOT NULL,
    PRIMARY KEY (doc_id, position)
);

CREATE TABLE IF NOT EXISTS doc_keys (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    key    TEXT NOT NULL,
    PRIMARY KEY (doc_id, key)
);
CREATE INDEX IF NOT EXISTS idx_doc_keys_key ON doc_keys(key);

CREATE TABLE IF NOT EXISTS postings (
    term      TEXT NOT NULL,
    doc_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tf        INTEGER NOT NULL,
    in_title  INTEGER NOT NULL DEFAULT 0,
    positions BLOB NOT NULL,
    PRIMARY KEY (term, doc_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_postings_doc ON postings(doc_id);

CREATE TABLE IF NOT EXISTS lexicon (
    kind  TEXT NOT NULL,
    text  TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (kind, text)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

DOC_COLUMNS = (
    "id, source, external_id, doi, title, abstract, year, published, venue, url, language, categories, "
    "cited_by_count, filename, job_id, length, ingested_at, ingested_via, cluster, pagerank, pagerank_pct, "
    "hub, authority, in_citations, out_citations, community"
)


def _positions_blob(title_terms: Sequence[str], body_terms: Sequence[str], gap: int) -> dict[str, tuple[array, bool]]:
    positions: dict[str, array] = {}
    for pos, term in enumerate(title_terms):
        positions.setdefault(term, array("I")).append(pos)
    offset = len(title_terms) + gap
    for pos, term in enumerate(body_terms):
        positions.setdefault(term, array("I")).append(offset + pos)
    titles = set(title_terms)
    return {term: (plist, term in titles) for term, plist in positions.items()}


class ShardStore:
    def __init__(self, path: Path):
        self.db = Database(path, SCHEMA)

    # ------------------------------------------------------------------ writes

    def known_hashes(self, hashes: Sequence[str]) -> set[str]:
        found: set[str] = set()
        for chunk in chunked(list(hashes)):
            rows = self.db.query(f"SELECT content_hash FROM documents WHERE content_hash IN ({placeholders(len(chunk))})", chunk)
            found.update(r[0] for r in rows)
        return found

    def insert(self, docs: Sequence[AnalyzedDocument], job_id: str | None, via: str, gap: int) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            for doc in docs:
                r = doc.record
                conn.execute(
                    "INSERT INTO documents (id, content_hash, source, external_id, doi, title, abstract, body, year,"
                    " published, venue, url, language, categories, cited_by_count, filename, job_id, length,"
                    " ingested_at, ingested_via) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (doc.id, doc.content_hash, r.source, r.external_id, r.doi, r.title, r.abstract, r.body or None,
                     r.year, r.published, r.venue, r.url, r.language, json.dumps(r.categories), r.cited_by_count,
                     r.filename, job_id, doc.length, now, via),
                )
                for position, name in enumerate(dict.fromkeys(a.strip() for a in r.authors if a.strip())):
                    conn.execute("INSERT OR IGNORE INTO authors (name, norm) VALUES (?, ?)", (name, fold(name)))
                    author_id = conn.execute("SELECT id FROM authors WHERE name = ?", (name,)).fetchone()[0]
                    conn.execute("INSERT OR IGNORE INTO document_authors VALUES (?, ?, ?)", (doc.id, author_id, position))
                conn.executemany("INSERT OR IGNORE INTO entities VALUES (?, ?, ?, ?)",
                                 [(doc.id, kind, value, count) for kind, value, count in doc.entities])
                conn.executemany("INSERT OR IGNORE INTO doc_references VALUES (?, ?, ?, ?, ?, ?)",
                                 [(doc.id, ref["position"], ref.get("raw"), ref.get("title"), ref.get("year"),
                                   json.dumps(ref["keys"])) for ref in doc.references])
                conn.executemany("INSERT OR IGNORE INTO doc_keys VALUES (?, ?)", [(doc.id, k) for k in doc.identity_keys])
                conn.executemany(
                    "INSERT INTO postings VALUES (?, ?, ?, ?, ?)",
                    [(term, doc.id, len(plist), int(in_title), plist.tobytes())
                     for term, (plist, in_title) in _positions_blob(doc.title_terms, doc.body_terms, gap).items()],
                )

    def add_lexicon(self, kind: str, counts: dict[str, int]) -> None:
        if not counts:
            return
        self.db.executemany(
            "INSERT INTO lexicon VALUES (?, ?, ?) ON CONFLICT(kind, text) DO UPDATE SET count = count + excluded.count",
            [(kind, text, count) for text, count in counts.items()],
        )

    def delete(self, doc_id: str) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            return cursor.rowcount > 0

    def update_metrics(self, rows: Sequence[tuple]) -> None:
        """rows: (pagerank, pagerank_pct, hub, authority, in, out, community, doc_id)."""
        self.db.executemany(
            "UPDATE documents SET pagerank=?, pagerank_pct=?, hub=?, authority=?, in_citations=?, out_citations=?,"
            " community=? WHERE id=?", rows)

    def update_clusters(self, assignments: dict[str, int]) -> None:
        self.db.executemany("UPDATE documents SET cluster=? WHERE id=?",
                            [(cluster, doc_id) for doc_id, cluster in assignments.items()])

    def set_meta(self, key: str, value) -> None:
        self.db.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, json.dumps(value)))

    def get_meta(self, key: str, default=None):
        value = self.db.scalar("SELECT value FROM meta WHERE key = ?", (key,))
        return json.loads(value) if value is not None else default

    # ------------------------------------------------------------------ reads

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM documents") or 0)

    def iter_postings(self) -> Iterator[tuple[str, str, bool, array]]:
        cursor = self.db.connection().execute("SELECT doc_id, term, in_title, positions FROM postings ORDER BY doc_id")
        for doc_id, term, in_title, blob in cursor:
            plist = array("I")
            plist.frombytes(blob)
            yield doc_id, term, bool(in_title), plist

    def iter_meta(self) -> Iterator[dict]:
        authors: dict[str, list[str]] = {}
        for doc_id, name in self.db.query(
                "SELECT da.doc_id, a.name FROM document_authors da JOIN authors a ON a.id = da.author_id"
                " ORDER BY da.doc_id, da.position"):
            authors.setdefault(doc_id, []).append(name)
        rows = self.db.query(
            "SELECT id, title, year, venue, source, doi, cluster, pagerank, pagerank_pct, in_citations,"
            " cited_by_count, length, ingested_at, job_id FROM documents")
        for row in rows:
            item = dict(row)
            item["authors"] = authors.get(item["id"], [])
            yield item

    def iter_lexicon(self) -> Iterator[tuple[str, str, int]]:
        yield from self.db.query("SELECT kind, text, count FROM lexicon")

    def _authors(self, ids: Sequence[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for chunk in chunked(list(ids)):
            rows = self.db.query(
                f"SELECT da.doc_id, a.name FROM document_authors da JOIN authors a ON a.id = da.author_id"
                f" WHERE da.doc_id IN ({placeholders(len(chunk))}) ORDER BY da.doc_id, da.position", chunk)
            for doc_id, name in rows:
                out.setdefault(doc_id, []).append(name)
        return out

    def summaries(self, ids: Sequence[str]) -> dict[str, dict]:
        """Card-sized rows (no body text) for search results and lists."""
        out: dict[str, dict] = {}
        for chunk in chunked(list(ids)):
            rows = self.db.query(f"SELECT {DOC_COLUMNS} FROM documents WHERE id IN ({placeholders(len(chunk))})", chunk)
            for row in rows:
                item = dict(row)
                item["categories"] = json.loads(item["categories"] or "[]")
                out[item["id"]] = item
        for doc_id, names in self._authors(list(out)).items():
            out[doc_id]["authors"] = names
        for item in out.values():
            item.setdefault("authors", [])
        return out

    def texts(self, ids: Sequence[str]) -> dict[str, tuple[str, str, str]]:
        out = {}
        for chunk in chunked(list(ids)):
            rows = self.db.query(
                f"SELECT id, title, abstract, substr(body, 1, 4000) FROM documents WHERE id IN ({placeholders(len(chunk))})",
                chunk)
            for doc_id, title, abstract, body in rows:
                out[doc_id] = (title or "", abstract or "", body or "")
        return out

    def document(self, doc_id: str) -> dict | None:
        row = self.db.query_one(f"SELECT {DOC_COLUMNS}, content_hash, length(body) AS body_length,"
                                " substr(body, 1, 20000) AS body FROM documents WHERE id = ?", (doc_id,))
        if row is None:
            return None
        doc = dict(row)
        doc["categories"] = json.loads(doc["categories"] or "[]")
        doc["authors"] = self._authors([doc_id]).get(doc_id, [])
        entities: dict[str, list] = {}
        for kind, value, count in self.db.query(
                "SELECT kind, value, count FROM entities WHERE doc_id = ? ORDER BY kind, rowid", (doc_id,)):
            entities.setdefault(kind, []).append({"value": value, "count": count})
        doc["entities"] = entities
        doc["references"] = [
            {"position": r["position"], "raw": r["raw"], "title": r["title"], "year": r["year"],
             "keys": json.loads(r["keys"])}
            for r in self.db.query("SELECT * FROM doc_references WHERE doc_id = ? ORDER BY position", (doc_id,))
        ]
        doc["identity_keys"] = [r[0] for r in self.db.query("SELECT key FROM doc_keys WHERE doc_id = ?", (doc_id,))]
        return doc

    def graph_records(self) -> Iterator[dict]:
        """Everything the leader needs to build the global citation graph."""
        keys: dict[str, list[str]] = {}
        for doc_id, key in self.db.query("SELECT doc_id, key FROM doc_keys"):
            keys.setdefault(doc_id, []).append(key)
        refs: dict[str, list] = {}
        for doc_id, position, title, ref_keys in self.db.query(
                "SELECT doc_id, position, title, keys FROM doc_references ORDER BY doc_id, position"):
            refs.setdefault(doc_id, []).append({"p": position, "t": title, "k": json.loads(ref_keys)})
        for meta in self.iter_meta():
            yield {
                "id": meta["id"], "title": meta["title"], "year": meta["year"], "authors": meta["authors"],
                "keys": keys.get(meta["id"], []), "refs": refs.get(meta["id"], []),
            }

    def recent(self, limit: int) -> list[dict]:
        rows = self.db.query("SELECT id FROM documents ORDER BY ingested_at DESC LIMIT ?", (limit,))
        ids = [r[0] for r in rows]
        found = self.summaries(ids)
        texts = self.texts(ids)
        for doc_id, item in found.items():
            title, abstract, body = texts.get(doc_id, ("", "", ""))
            item["abstract"] = (abstract or body)[:700]
        return [found[i] for i in ids if i in found]

    def entity_counts(self) -> dict[str, int]:
        return {kind: count for kind, count in self.db.query("SELECT kind, COUNT(*) FROM entities GROUP BY kind")}

    def size_bytes(self) -> int:
        path = self.db.path
        return sum(p.stat().st_size for p in (path, Path(f"{path}-wal")) if p.exists())
