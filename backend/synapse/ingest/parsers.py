"""File processing: turn raw dataset files into :class:`RawRecord` objects.

Supported inputs: CSV/TSV (e.g. arXiv exports), JSON / JSON Lines (OpenAlex,
the arXiv Kaggle snapshot, or any list of objects), plain text / Markdown /
HTML papers, PDF, arXiv Atom XML, and ``.zip`` / ``.tar`` / ``.gz`` archives of
any of those.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

from ..text import extract
from .records import RawRecord
from .sources import ArxivClient

log = logging.getLogger(__name__)

SYNAPSE_FORMAT = "synapse/1"
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".tex"}
HTML_EXTENSIONS = {".html", ".htm"}
SUPPORTED_EXTENSIONS = (
    {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".pdf", ".xml", ".atom", ".zip", ".tar", ".tgz", ".gz"}
    | TEXT_EXTENSIONS
    | HTML_EXTENSIONS
)
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ARCHIVE_MEMBERS = 50_000
MAX_BODY_CHARS = 400_000

ARXIV_ID_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$", re.IGNORECASE)
OPENALEX_ID_RE = re.compile(r"(?:https?://openalex\.org/)?(W\d{4,})$", re.IGNORECASE)

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "display_name", "paper_title", "name", "headline"),
    "abstract": ("abstract", "summary", "description", "abstract_text", "snippet"),
    "body": ("body", "text", "content", "full_text", "fulltext", "article"),
    "authors": ("authors", "author", "creators", "creator", "author_names", "authorships"),
    "year": ("year", "publication_year", "pub_year"),
    "published": ("published", "publication_date", "date", "pub_date", "update_date", "created", "submitted"),
    "doi": ("doi",),
    "external_id": ("id", "paper_id", "arxiv_id", "openalex_id", "pmid", "pubmed_id", "uid"),
    "venue": ("venue", "journal", "journal_ref", "journal-ref", "conference", "booktitle", "container_title", "publisher"),
    "url": ("url", "link", "pdf_url", "landing_page_url"),
    "categories": ("categories", "category", "topics", "fields", "subjects", "tags", "primary_category"),
    "keywords": ("keywords", "keyword", "key_words"),
    "references": ("references", "referenced_works", "citations", "refs", "cites"),
    "cited_by_count": ("cited_by_count", "citation_count", "citations_count", "n_citations", "cited_by"),
    "language": ("language", "lang"),
}


# --------------------------------------------------------------------------- helpers


def _year(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2100 else None
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", str(value))
    return int(match.group(1)) if match else None


def _int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        separator = ";" if ";" in value else "|" if "|" in value else ","
        if separator == "," and value.count(" ") > 3 * value.count(","):
            return [value]
        return [part.strip() for part in value.split(separator) if part.strip()]
    return [value]


def _names(value) -> list[str]:
    """Authors from strings, lists of strings or lists of dicts (OpenAlex/Crossref style)."""
    if isinstance(value, str):
        if ";" in value:
            names = value.split(";")
        else:
            names = re.split(r",|\s+and\s+|\s*&\s*", value)
        return [" ".join(n.split()) for n in names if n.strip()]
    names = []
    for item in value or []:
        if isinstance(item, str):
            names.append(item.strip())
        elif isinstance(item, dict):
            author = item.get("author") if isinstance(item.get("author"), dict) else item
            name = author.get("display_name") or author.get("name")
            if not name and (author.get("given") or author.get("family")):
                name = f"{author.get('given', '')} {author.get('family', '')}"
            if name:
                names.append(" ".join(str(name).split()))
        elif isinstance(item, (list, tuple)) and item:  # arXiv "authors_parsed": [last, first, suffix]
            names.append(" ".join(p for p in (item[1] if len(item) > 1 else "", item[0]) if p).strip())
    return [n for n in names if n]


def _reference(item) -> dict | None:
    if isinstance(item, dict):
        return {k: v for k, v in item.items() if k in {"key", "raw", "title", "year", "doi"}} or None
    text = str(item).strip()
    if not text:
        return None
    oa = OPENALEX_ID_RE.search(text)
    if oa and len(text) < 60:
        return {"key": f"oa:{oa.group(1).upper()}"}
    doi = extract.normalize_doi(text)
    if doi and " " not in text:
        return {"key": f"doi:{doi}"}
    arxiv = ARXIV_ID_RE.match(text)
    if arxiv:
        return {"key": f"arxiv:{arxiv.group(1)}"}
    return {"raw": text[:1000]}


def _external_id(value, source: str) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    oa = OPENALEX_ID_RE.search(text)
    if oa:
        return f"openalex:{oa.group(1).upper()}"
    arxiv = ARXIV_ID_RE.match(text)
    if arxiv:
        return f"arxiv:{arxiv.group(1)}"
    return f"{source}:{text}"


# --------------------------------------------------------------------------- known formats


def reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex stores abstracts as an inverted index ``{word: [positions]}``; invert it back."""
    if not inverted_index:
        return ""
    placed = sorted((pos, word) for word, positions in inverted_index.items() for pos in positions)
    return " ".join(word for _, word in placed)


def normalize_openalex(work: dict) -> RawRecord:
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    topic = work.get("primary_topic") or {}
    categories = [
        topic.get("display_name"),
        (topic.get("subfield") or {}).get("display_name"),
        (topic.get("field") or {}).get("display_name"),
    ]
    oa_id = work["id"].rsplit("/", 1)[-1]
    return RawRecord(
        title=extract.flatten(work.get("display_name") or work.get("title") or ""),
        abstract=extract.strip_boilerplate(extract.flatten(reconstruct_abstract(work.get("abstract_inverted_index")))),
        authors=_names(work.get("authorships") or []),
        year=work.get("publication_year"),
        published=work.get("publication_date"),
        doi=extract.normalize_doi(work.get("doi")),
        external_id=f"openalex:{oa_id}",
        source="openalex",
        venue=source.get("display_name"),
        url=location.get("landing_page_url") or work.get("doi") or work["id"],
        language=work.get("language"),
        categories=[c for c in categories if c],
        keywords=[k.get("display_name") for k in work.get("keywords") or [] if k.get("display_name")],
        references=[{"key": f"oa:{r.rsplit('/', 1)[-1]}"} for r in work.get("referenced_works") or []],
        cited_by_count=work.get("cited_by_count"),
    )


def normalize_arxiv(entry: dict) -> RawRecord:
    """arXiv API entries (see :class:`ArxivClient`) and arXiv Kaggle snapshot rows."""
    arxiv_id = str(entry.get("arxiv_id") or entry.get("id") or "").strip()
    versions = entry.get("versions") or []
    published = entry.get("published") or (versions[0].get("created") if versions else None) or entry.get("update_date")
    categories = entry.get("categories") or []
    if isinstance(categories, str):
        categories = categories.split()
    authors = entry.get("authors_parsed") or entry.get("authors") or []
    return RawRecord(
        title=extract.flatten(entry.get("title")),
        abstract=extract.flatten(entry.get("abstract")),
        authors=_names(authors),
        year=_year(published),
        published=str(published)[:32] if published else None,
        doi=extract.normalize_doi(entry.get("doi")),
        external_id=f"arxiv:{arxiv_id}" if arxiv_id else None,
        source="arxiv",
        venue=entry.get("journal_ref") or entry.get("journal-ref") or "arXiv",
        url=entry.get("url") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None),
        categories=list(categories),
    )


def record_from_mapping(obj: dict, source: str = "json", filename: str | None = None) -> RawRecord | None:
    """Map any dict-shaped row onto a RawRecord, recognising known schemas first."""
    if not isinstance(obj, dict):
        return None
    if obj.get("format") == SYNAPSE_FORMAT:
        record = RawRecord.from_dict(obj)
    elif str(obj.get("id", "")).startswith("https://openalex.org/W") or "authorships" in obj:
        record = normalize_openalex(obj)
    elif "authors_parsed" in obj or ("submitter" in obj and "categories" in obj) or "arxiv_id" in obj:
        record = normalize_arxiv(obj)
    else:
        lowered = {str(k).strip().lower(): v for k, v in obj.items()}

        def pick(name: str):
            for alias in FIELD_ALIASES[name]:
                value = lowered.get(alias)
                if value not in (None, "", []):
                    return value
            return None

        published = pick("published")
        record = RawRecord(
            title=extract.flatten(str(pick("title") or "")),
            abstract=extract.strip_boilerplate(extract.flatten(str(pick("abstract") or ""))),
            body=extract.clean_text(str(pick("body") or ""))[:MAX_BODY_CHARS],
            authors=_names(pick("authors")),
            year=_year(pick("year")) or _year(published),
            published=str(published) if published else None,
            doi=extract.normalize_doi(str(pick("doi") or "")),
            external_id=_external_id(pick("external_id"), source),
            source=source,
            venue=str(pick("venue")) if pick("venue") else None,
            url=str(pick("url")) if pick("url") else None,
            language=str(pick("language")) if pick("language") else None,
            categories=[str(c) for c in _as_list(pick("categories"))],
            keywords=[str(k) for k in _as_list(pick("keywords"))],
            references=[r for r in map(_reference, _as_list(pick("references"))) if r],
            cited_by_count=_int(pick("cited_by_count")),
        )
    if filename:
        record.filename = filename
    if not record.title and not record.abstract and not record.body:
        return None
    return record


def record_from_text(text: str, filename: str | None = None, source: str = "txt") -> RawRecord | None:
    """A raw paper-like text: everything is recovered with regex extraction."""
    found = extract.extract_document(text)
    if not found.body.strip():
        return None
    title = found.title or (Path(filename).stem.replace("_", " ") if filename else "Untitled document")
    references = [
        {"raw": ref.raw, "title": ref.title, "year": ref.year, "doi": ref.doi,
         "key": ref.keys()[0] if ref.keys() else None}
        for ref in found.references
    ]
    return RawRecord(
        title=title,
        abstract=found.abstract or "",
        body=found.body[:MAX_BODY_CHARS],
        authors=found.authors,
        year=found.year,
        doi=found.doi,
        source=source,
        keywords=found.keywords,
        references=references,
        filename=filename,
    )


# --------------------------------------------------------------------------- file formats


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_csv_text(text: str, filename: str | None = None, delimiter: str | None = None) -> Iterator[RawRecord]:
    sample = text[:20_000]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    for row in reader:
        record = record_from_mapping({k: v for k, v in row.items() if k}, source="csv", filename=filename)
        if record:
            yield record


def parse_json_text(text: str, filename: str | None = None) -> Iterator[RawRecord]:
    stripped = text.lstrip()
    if not stripped:
        return
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None  # probably JSON Lines
        if data is not None:
            if isinstance(data, dict):
                items = data.get("results") or data.get("data") or data.get("records") or data.get("documents") or [data]
            else:
                items = data
            for obj in items:
                record = record_from_mapping(obj, source="json", filename=filename)
                if record:
                    yield record
            return
    for line_number, line in enumerate(stripped.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            log.warning("%s:%d is not valid JSON, skipped", filename, line_number)
            continue
        record = record_from_mapping(obj, source="json", filename=filename)
        if record:
            yield record


def parse_pdf_bytes(data: bytes, filename: str | None = None) -> Iterator[RawRecord]:
    from pypdf import PdfReader  # imported lazily: only needed for PDFs

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(pages)
    meta = reader.metadata or {}
    record = record_from_text(text, filename=filename, source="pdf")
    if record:
        meta_title = (meta.get("/Title") or "").strip() if hasattr(meta, "get") else ""
        if meta_title and len(meta_title.split()) >= 3:
            record.title = extract.flatten(meta_title)
        meta_author = (meta.get("/Author") or "").strip() if hasattr(meta, "get") else ""
        if meta_author and not record.authors:
            record.authors = extract.split_names(meta_author)
        yield record


def parse_bytes(data: bytes, filename: str, depth: int = 0) -> Iterator[RawRecord]:
    """Dispatch on the file extension (archives recurse into their members)."""
    name = PurePosixPath(filename).name
    suffix = PurePosixPath(name).suffix.lower()

    if suffix == ".gz":
        inner = name[:-3]
        if inner.lower().endswith(".tar"):
            yield from _parse_tar(data, depth)
        else:
            yield from parse_bytes(gzip.decompress(data), inner, depth)
    elif suffix in {".tar", ".tgz"}:
        yield from _parse_tar(data, depth)
    elif suffix == ".zip":
        yield from _parse_zip(data, depth)
    elif suffix in {".csv", ".tsv"}:
        yield from parse_csv_text(_decode(data), name, delimiter="\t" if suffix == ".tsv" else None)
    elif suffix in {".json", ".jsonl", ".ndjson"}:
        yield from parse_json_text(_decode(data), name)
    elif suffix in {".xml", ".atom"}:
        for entry in ArxivClient.parse_feed(data):
            record = normalize_arxiv(entry)
            record.filename = name
            yield record
    elif suffix == ".pdf":
        yield from parse_pdf_bytes(data, name)
    elif suffix in HTML_EXTENSIONS:
        record = record_from_text(extract.strip_html(_decode(data)), name, source="html")
        if record:
            yield record
    elif suffix in TEXT_EXTENSIONS or not suffix:
        record = record_from_text(_decode(data), name, source="txt")
        if record:
            yield record
    else:
        raise ValueError(f"Unsupported file type: {name}")


def _archive_members_ok(sizes: Iterable[int], count: int) -> None:
    if count > MAX_ARCHIVE_MEMBERS or sum(sizes) > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive is too large to ingest safely")


def _parse_zip(data: bytes, depth: int) -> Iterator[RawRecord]:
    if depth > 2:
        return
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        _archive_members_ok((m.file_size for m in members), len(members))
        for member in members:
            if _skip_member(member.filename):
                continue
            yield from parse_bytes(archive.read(member), member.filename, depth + 1)


def _parse_tar(data: bytes, depth: int) -> Iterator[RawRecord]:
    if depth > 2:
        return
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        members = [m for m in archive.getmembers() if m.isfile()]
        _archive_members_ok((m.size for m in members), len(members))
        for member in members:
            if _skip_member(member.name):
                continue
            handle = archive.extractfile(member)
            if handle is not None:
                yield from parse_bytes(handle.read(), member.name, depth + 1)


def _skip_member(name: str) -> bool:
    base = PurePosixPath(name).name
    suffix = PurePosixPath(base).suffix.lower()
    return base.startswith(".") or "__MACOSX" in name or suffix not in SUPPORTED_EXTENSIONS


def parse_file(path: Path, display_name: str | None = None) -> list[RawRecord]:
    """Parse one file from disk into records."""
    return list(parse_bytes(path.read_bytes(), display_name or path.name))


def is_supported(filename: str) -> bool:
    name = filename.lower()
    if name.endswith(".gz"):
        name = name[:-3]
        if not name or "." not in name:
            return True
    return PurePosixPath(name).suffix in SUPPORTED_EXTENSIONS or name.endswith(".tar")
