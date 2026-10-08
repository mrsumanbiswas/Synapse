"""The record format that flows from parsers to shard nodes."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, fields

from ..text.extract import normalize_doi, normalize_title


@dataclass
class RawRecord:
    """One document as read from a source, before analysis.

    Records travel between peers as plain dicts, so every field is JSON friendly.
    ``references`` holds dicts with any of ``key``/``raw``/``title``/``year``/``doi``.
    """

    title: str = ""
    abstract: str = ""
    body: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    published: str | None = None
    doi: str | None = None
    external_id: str | None = None
    source: str = "file"
    venue: str | None = None
    url: str | None = None
    language: str | None = None
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    cited_by_count: int | None = None
    filename: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RawRecord":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def dedup_key(self) -> str:
        """Stable identity: DOI, then external id, then title + first author + year."""
        doi = normalize_doi(self.doi)
        if doi:
            return f"doi:{doi}"
        if self.external_id:
            return f"ext:{self.external_id.lower()}"
        first_author = self.authors[0].split()[-1].lower() if self.authors else ""
        return f"title:{normalize_title(self.title)}|{first_author}|{self.year or ''}"

    def content_hash(self) -> str:
        return hashlib.sha1(self.dedup_key().encode()).hexdigest()

    def identity_keys(self) -> list[str]:
        """Keys other documents may use to cite this one."""
        keys = []
        doi = normalize_doi(self.doi)
        if doi:
            keys.append(f"doi:{doi}")
        if self.external_id:
            prefix, _, value = self.external_id.partition(":")
            if prefix == "openalex":
                keys.append(f"oa:{value}")
            elif prefix == "arxiv":
                keys.append(f"arxiv:{value}")
        title = normalize_title(self.title)
        if title:
            keys.append(f"title:{title}")
        return keys
