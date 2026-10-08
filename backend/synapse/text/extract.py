"""Information extraction and cleaning with regular expressions.

Pulls structured facts out of raw scraped text: e-mails, URLs, DOIs, arXiv ids,
numeric citation markers (``[1]``, ``[2, 4]``, ``[3-5]``), author-year
citations, the reference list, abstract, keywords, title and authors.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"'`{}|\\^\[\]]+", re.IGNORECASE)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"\barXiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)", re.IGNORECASE
)
CITATION_RE = re.compile(r"\[(\s*\d{1,3}(?:\s*[-–,;]\s*\d{1,3})*\s*)\]")
AUTHOR_YEAR_RE = re.compile(
    r"\(([A-Z][A-Za-z'\-]+(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z'\-]+)?),?\s+((?:19|20)\d{2})[a-z]?\)"
)
YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
EXPLICIT_YEAR_RE = re.compile(
    r"^[ \t]*(?:year|published|date|publication date)[ \t]*:[ \t]*.*?\b(1[89]\d{2}|20\d{2})\b",
    re.IGNORECASE | re.MULTILINE,
)
REFERENCES_HEADING_RE = re.compile(
    r"^[ \t]*(?:\d+\.?[ \t]*)?(?:references|bibliography|works cited|literature cited)[ \t]*:?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
NUMBERED_REF_RE = re.compile(r"^[ \t]*\[(\d{1,3})\][ \t]*(.+?)(?=^[ \t]*\[\d{1,3}\]|\Z)", re.MULTILINE | re.DOTALL)
DOTTED_REF_RE = re.compile(r"^[ \t]*(\d{1,3})\.[ \t]+(.+?)(?=^[ \t]*\d{1,3}\.[ \t]+|\Z)", re.MULTILINE | re.DOTALL)
ABSTRACT_RE = re.compile(
    r"^[ \t]*abstract\b[ \t]*[:.\-—]?[ \t]*\n?(.+?)(?:\n[ \t]*\n|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
KEYWORDS_RE = re.compile(r"^[ \t]*(?:keywords|key words|index terms)[ \t]*[:.\-—][ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)
AUTHORS_LINE_RE = re.compile(r"^[ \t]*(?:authors?|by)[ \t]*:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)
TITLE_LINE_RE = re.compile(r"^[ \t]*title[ \t]*:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)
OWN_DOI_RE = re.compile(r"^[ \t]*doi[ \t]*[:=][ \t]*(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)", re.IGNORECASE | re.MULTILINE)
QUOTED_TITLE_RE = re.compile(r"[\"“]([^\"”]{8,300}?)[,.]?[\"”]")
# Split "Authors. Title. Venue." on full stops, but not after initials such as "C. S. Yang".
SENTENCE_SPLIT_RE = re.compile(r"(?<!\b[A-Z])\.\s+(?=[A-Z0-9(\"“])")

SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
BLOCK_TAG_RE = re.compile(r"<\s*(?:br|/p|/div|/h\d|/li|/tr)\b[^>]*>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
HYPHEN_BREAK_RE = re.compile(r"(\w)-\n[ \t]*(\w)")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SPACES_RE = re.compile(r"[ \t  ​]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_TRAILING = ".,;:!?)]}'\">"
# Publisher notices that trail many abstracts: "© 1990 John Wiley & Sons, Inc.",
# "Copyright (c) 2015 Elsevier B.V. All rights reserved."
COPYRIGHT_RE = re.compile(
    r"(?:\s*(?:©|\(c\)|copyright\b)[^©]{0,40}?\b(?:19|20)\d{2}\b.{0,160}$)|(?:\s*all rights reserved\.?\s*$)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- cleaning


def clean_text(text: str | None) -> str:
    """Normalise unicode, join hyphenated line breaks, collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)  # also expands PDF ligatures like "ﬁ"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_RE.sub("", text)
    text = HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = SPACES_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return BLANK_LINES_RE.sub("\n\n", text).strip()


def flatten(text: str | None) -> str:
    """Clean and put everything on one line (for abstracts and titles)."""
    return " ".join(clean_text(text).split())


def strip_boilerplate(text: str) -> str:
    """Drop trailing copyright notices from an abstract."""
    previous = None
    while text and text != previous:
        previous = text
        text = COPYRIGHT_RE.sub("", text).rstrip()
    return text


def strip_html(text: str) -> str:
    text = SCRIPT_STYLE_RE.sub(" ", text)
    text = BLOCK_TAG_RE.sub("\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    return html.unescape(text)


def normalize_title(title: str | None) -> str:
    """Canonical form used to match references to documents."""
    if not title:
        return ""
    decomposed = unicodedata.normalize("NFKD", title)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return NON_ALNUM_RE.sub(" ", ascii_text).strip()


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    doi = doi.rstrip(_TRAILING).lower()
    return doi if doi.startswith("10.") else None


def _unique(items) -> list:
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# --------------------------------------------------------------------------- entities


def extract_emails(text: str) -> list[str]:
    return _unique(m.group().lower() for m in EMAIL_RE.finditer(text))


def extract_urls(text: str) -> list[str]:
    return _unique(m.group().rstrip(_TRAILING) for m in URL_RE.finditer(text))


def extract_dois(text: str) -> list[str]:
    return _unique(normalize_doi(m.group(1)) for m in DOI_RE.finditer(text))


def extract_arxiv_ids(text: str) -> list[str]:
    return _unique(m.group(1) for m in ARXIV_RE.finditer(text))


def extract_citation_markers(text: str) -> dict[int, int]:
    """How often each numbered reference is cited, e.g. ``[1]``, ``[2, 5]``, ``[3-6]``."""
    counts: Counter[int] = Counter()
    for match in CITATION_RE.finditer(text):
        for part in re.split(r"[,;]", match.group(1)):
            part = part.strip()
            bounds = re.split(r"\s*[-–]\s*", part)
            if len(bounds) == 2:
                lo, hi = int(bounds[0]), int(bounds[1])
                if 0 < lo <= hi and hi - lo <= 50:
                    counts.update(range(lo, hi + 1))
            elif part.isdigit():
                counts[int(part)] += 1
    return dict(sorted(counts.items()))


def extract_author_year_citations(text: str) -> list[str]:
    return _unique(f"{m.group(1)}, {m.group(2)}" for m in AUTHOR_YEAR_RE.finditer(text))


def extract_years(text: str) -> list[int]:
    return [int(y) for y in YEAR_RE.findall(text)]


# --------------------------------------------------------------------------- structure


@dataclass
class Reference:
    number: int | None
    raw: str
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    arxiv: str | None = None

    def keys(self) -> list[str]:
        """Identifiers used to resolve the reference against the corpus."""
        keys = []
        if self.doi:
            keys.append(f"doi:{self.doi}")
        if self.arxiv:
            keys.append(f"arxiv:{re.sub(r'v\d+$', '', self.arxiv)}")
        if self.title:
            keys.append(f"title:{normalize_title(self.title)}")
        return keys


def split_references(text: str) -> tuple[str, str]:
    """Split a paper into (body, reference section) at the last "References" heading."""
    matches = list(REFERENCES_HEADING_RE.finditer(text))
    if not matches:
        return text, ""
    last = matches[-1]
    return text[: last.start()].rstrip(), text[last.end():].strip()


def guess_reference_title(raw: str) -> str | None:
    quoted = QUOTED_TITLE_RE.search(raw)
    if quoted:
        return quoted.group(1).strip(" ,.")
    parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(raw) if p.strip()]
    if len(parts) < 2:
        return None
    candidate = parts[1].rstrip(".")
    # An author-year entry may put "(1975)" at the end of the author block.
    if re.fullmatch(r"\(?\d{4}[a-z]?\)?", candidate):
        candidate = parts[2].rstrip(".") if len(parts) > 2 else ""
    return candidate if len(candidate.split()) >= 2 else None


def parse_references(section: str) -> list[Reference]:
    if not section:
        return []
    entries = [(int(n), body) for n, body in NUMBERED_REF_RE.findall(section)]
    if not entries:
        entries = [(int(n), body) for n, body in DOTTED_REF_RE.findall(section)]
    if not entries:
        lines = [line for line in section.split("\n") if len(line.split()) >= 4]
        entries = [(None, line) for line in lines]

    references = []
    for number, body in entries:
        raw = " ".join(body.split())
        if not raw:
            continue
        years = extract_years(raw)
        dois = extract_dois(raw)
        arxiv = extract_arxiv_ids(raw)
        references.append(Reference(
            number=number,
            raw=raw[:1000],
            title=guess_reference_title(raw),
            year=years[-1] if years else None,
            doi=dois[0] if dois else None,
            arxiv=arxiv[0] if arxiv else None,
        ))
    return references


def extract_abstract(text: str) -> str | None:
    match = ABSTRACT_RE.search(text)
    if not match:
        return None
    abstract = flatten(match.group(1))
    return abstract if len(abstract.split()) >= 10 else None


def extract_keywords(text: str) -> list[str]:
    match = KEYWORDS_RE.search(text)
    if not match:
        return []
    return _unique(k.strip(" .").lower() for k in re.split(r"[,;·•]", match.group(1)))


def guess_title(text: str) -> str | None:
    explicit = TITLE_LINE_RE.search(text[:2000])
    if explicit:
        return flatten(explicit.group(1))
    for line in text.split("\n")[:15]:
        line = line.strip().strip("#").strip()
        if not line or len(line) > 250 or len(line.split()) < 2:
            continue
        if re.match(r"(?i)^(abstract|authors?|by|keywords?|arxiv|doi)\b", line) or EMAIL_RE.search(line):
            continue
        return line
    return None


def _looks_like_name(name: str) -> bool:
    tokens = name.split()
    return 1 <= len(tokens) <= 5 and all(t[0].isupper() and not any(c.isdigit() for c in t) for t in tokens)


def split_names(value: str) -> list[str]:
    value = re.sub(r"\s+(?:and|&)\s+", ", ", value)
    names = [n.strip(" .,*0-9†‡") for n in re.split(r"[,;]", value)]
    return [n for n in names if n and len(n) <= 80]


def guess_authors(text: str, title: str | None = None) -> list[str]:
    explicit = AUTHORS_LINE_RE.search(text[:3000])
    if explicit:
        return split_names(explicit.group(1))
    lines = [line.strip() for line in text.split("\n")[:12] if line.strip()]
    if title and title in lines:
        candidates = lines[lines.index(title) + 1 : lines.index(title) + 3]
        for line in candidates:
            if re.match(r"(?i)^abstract\b", line) or EMAIL_RE.search(line) or re.search(r"\d", line):
                continue
            names = split_names(line)
            if names and all(_looks_like_name(n) for n in names):
                return names
    return []


def guess_year(text: str) -> int | None:
    explicit = EXPLICIT_YEAR_RE.search(text[:5000])
    if explicit:
        return int(explicit.group(1))
    header_years = extract_years(text[:1500])
    return max(header_years) if header_years else None


def _own_doi(text: str) -> str | None:
    """Only a "DOI: ..." line in the header identifies the paper itself; DOIs in the
    body are mentions of other work."""
    match = OWN_DOI_RE.search(text[:2500])
    return normalize_doi(match.group(1)) if match else None


@dataclass
class Extraction:
    """Everything the extractor found in one raw text."""

    title: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)
    year: int | None = None
    body: str = ""
    emails: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    doi: str | None = None
    dois: list[str] = field(default_factory=list)
    arxiv_ids: list[str] = field(default_factory=list)
    citation_markers: dict[int, int] = field(default_factory=dict)
    author_year_citations: list[str] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def extract_document(text: str) -> Extraction:
    """Run the full extraction pipeline over a raw paper-like text."""
    text = clean_text(text)
    body, reference_section = split_references(text)
    title = guess_title(body)
    return Extraction(
        title=title,
        authors=guess_authors(body, title),
        abstract=extract_abstract(body),
        keywords=extract_keywords(body),
        year=guess_year(body),
        doi=_own_doi(body),
        body=body,
        emails=extract_emails(text),
        urls=extract_urls(text),
        dois=extract_dois(body),
        arxiv_ids=extract_arxiv_ids(body),
        citation_markers=extract_citation_markers(body),
        author_year_citations=extract_author_year_citations(body),
        references=parse_references(reference_section),
    )
