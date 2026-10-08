"""Remote data sources: FTP servers, the OpenAlex API and the arXiv API."""

from __future__ import annotations

import fnmatch
import ftplib
import json
import logging
import posixpath
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .. import __version__

log = logging.getLogger(__name__)
USER_AGENT = f"Synapse/{__version__} (research search engine; +https://github.com/)"


# --------------------------------------------------------------------------- FTP


@dataclass
class FtpEntry:
    name: str
    path: str
    size: int | None
    is_dir: bool
    modified: str | None = None


def _ftp_connect(host: str, port: int, user: str, password: str, timeout: float) -> ftplib.FTP:
    ftp = ftplib.FTP(timeout=timeout)
    ftp.connect(host, port)
    ftp.login(user or "anonymous", password or "anonymous@")
    ftp.set_pasv(True)
    return ftp


def ftp_list(host: str, port: int = 21, user: str = "anonymous", password: str = "",
             path: str = "/", timeout: float = 20.0) -> list[FtpEntry]:
    """List a remote directory (MLSD when the server supports it, else NLST)."""
    with _ftp_connect(host, port, user, password, timeout) as ftp:
        entries: list[FtpEntry] = []
        try:
            for name, facts in ftp.mlsd(path, facts=["type", "size", "modify"]):
                if name in (".", ".."):
                    continue
                entries.append(FtpEntry(
                    name=name,
                    path=posixpath.join(path, name),
                    size=int(facts["size"]) if facts.get("size") else None,
                    is_dir=facts.get("type") == "dir",
                    modified=facts.get("modify"),
                ))
        except ftplib.error_perm:
            for full in ftp.nlst(path):
                name = posixpath.basename(full)
                try:
                    size = ftp.size(full)
                    is_dir = False
                except ftplib.error_perm:
                    size, is_dir = None, True
                entries.append(FtpEntry(name=name, path=full, size=size, is_dir=is_dir))
    return sorted(entries, key=lambda e: (not e.is_dir, e.name))


def ftp_expand(host: str, port: int, user: str, password: str, path: str,
               pattern: str = "*", depth: int = 2) -> list[FtpEntry]:
    """Resolve a remote path to the files to download (a file, or a directory walked ``depth`` levels)."""
    parent = posixpath.dirname(path.rstrip("/")) or "/"
    listing = ftp_list(host, port, user, password, parent)
    match = next((e for e in listing if e.path.rstrip("/") == path.rstrip("/")), None)
    if match is not None and not match.is_dir:
        return [match]

    files: list[FtpEntry] = []
    stack = [(path, 0)]
    while stack:
        directory, level = stack.pop()
        for entry in ftp_list(host, port, user, password, directory):
            if entry.is_dir and level + 1 < depth:
                stack.append((entry.path, level + 1))
            elif not entry.is_dir and fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                files.append(entry)
    return files


def ftp_download(host: str, port: int, user: str, password: str, remote_paths: list[str],
                 dest_dir: Path, workers: int = 4,
                 on_file: Callable[[str, Path | None, Exception | None], None] | None = None,
                 timeout: float = 60.0) -> list[Path]:
    """Download files concurrently; every worker thread opens its own FTP session."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    def fetch(remote: str) -> Path:
        local = dest_dir / posixpath.basename(remote)
        with _ftp_connect(host, port, user, password, timeout) as ftp, open(local, "wb") as fh:
            ftp.retrbinary(f"RETR {remote}", fh.write, blocksize=64 * 1024)
        return local

    paths: list[Path] = []
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="ftp") as pool:
        futures = {pool.submit(fetch, remote): remote for remote in remote_paths}
        for future in as_completed(futures):
            remote = futures[future]
            try:
                local = future.result()
                paths.append(local)
                if on_file:
                    on_file(remote, local, None)
            except Exception as exc:  # noqa: BLE001 - reported per file
                log.warning("FTP download failed for %s: %s", remote, exc)
                if on_file:
                    on_file(remote, None, exc)
    return paths


# --------------------------------------------------------------------------- HTTP helpers


class _Throttle:
    def __init__(self, interval: float):
        self.interval = interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def _http_get(url: str, throttle: _Throttle, timeout: float, accept: str) -> tuple[bytes, dict]:
    for attempt in range(5):
        throttle.wait()
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
            with urlopen(request, timeout=timeout) as response:
                return response.read(), dict(response.headers)
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 4:
                wait = float(exc.headers.get("Retry-After") or 2 ** attempt)
                log.info("HTTP %s from %s, retrying in %.0fs", exc.code, url.split("?")[0], wait)
                time.sleep(min(wait, 30))
                continue
            raise
        except URLError:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("unreachable")


# --------------------------------------------------------------------------- OpenAlex


class OpenAlexClient:
    """Minimal OpenAlex works client (CC0 scholarly metadata, https://openalex.org)."""

    BASE_URL = "https://api.openalex.org"
    SELECT = (
        "id,doi,display_name,publication_year,publication_date,authorships,"
        "abstract_inverted_index,referenced_works,cited_by_count,primary_location,"
        "primary_topic,keywords,language,type"
    )

    def __init__(self, api_key: str | None = None, timeout: float = 30.0, interval: float = 0.15):
        self.api_key = api_key
        self.timeout = timeout
        self._throttle = _Throttle(interval)
        self.remaining_credits: str | None = None

    def _get(self, path: str, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{self.BASE_URL}{path}?{urlencode(params, safe=':,|')}"
        body, headers = _http_get(url, self._throttle, self.timeout, "application/json")
        self.remaining_credits = headers.get("x-ratelimit-remaining") or headers.get("X-RateLimit-Remaining")
        return json.loads(body)

    def list_works(self, filter: str | None = None, search: str | None = None,
                   sort: str | None = None, per_page: int = 25) -> list[dict]:
        data = self._get("/works", filter=filter, search=search, sort=sort,
                         per_page=min(per_page, 200), select=self.SELECT)
        return data.get("results", [])

    def iter_works(self, filter: str | None = None, search: str | None = None,
                   sort: str | None = None, limit: int = 100) -> Iterator[dict]:
        cursor, seen = "*", 0
        while cursor and seen < limit:
            data = self._get("/works", filter=filter, search=search, sort=sort, cursor=cursor,
                             per_page=min(200, limit - seen), select=self.SELECT)
            results = data.get("results", [])
            if not results:
                return
            for work in results:
                yield work
                seen += 1
                if seen >= limit:
                    return
            cursor = data.get("meta", {}).get("next_cursor")

    def _batched(self, field: str, values: list[str], batch: int = 50) -> list[dict]:
        works = []
        for i in range(0, len(values), batch):
            chunk = values[i : i + batch]
            works.extend(self.list_works(filter=f"{field}:{'|'.join(chunk)}", per_page=len(chunk)))
        return works

    def works_by_ids(self, ids: list[str]) -> list[dict]:
        return self._batched("openalex", [i.rsplit("/", 1)[-1] for i in ids])

    def works_by_dois(self, dois: list[str]) -> list[dict]:
        return self._batched("doi", dois)


# --------------------------------------------------------------------------- arXiv


class ArxivClient:
    """arXiv Atom API client (metadata is CC0). arXiv asks for one request every 3 seconds."""

    BASE_URL = "https://export.arxiv.org/api/query"
    NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    def __init__(self, timeout: float = 30.0, interval: float = 3.0):
        self.timeout = timeout
        self._throttle = _Throttle(interval)

    def search(self, query: str, max_results: int = 50, start: int = 0,
               sort_by: str = "relevance") -> list[dict]:
        params = {"search_query": query, "start": start, "max_results": min(max_results, 500),
                  "sortBy": sort_by, "sortOrder": "descending"}
        body, _ = _http_get(f"{self.BASE_URL}?{urlencode(params)}", self._throttle,
                            self.timeout, "application/atom+xml")
        return self.parse_feed(body)

    @classmethod
    def parse_feed(cls, xml_bytes: bytes | str) -> list[dict]:
        root = ET.fromstring(xml_bytes)
        entries = []
        for entry in root.findall("a:entry", cls.NS):
            def text(tag: str) -> str:
                node = entry.find(tag, cls.NS)
                return " ".join(node.text.split()) if node is not None and node.text else ""

            raw_id = text("a:id")
            if not raw_id or "/abs/" not in raw_id:
                continue
            arxiv_id = raw_id.rsplit("/abs/", 1)[1]
            base_id = arxiv_id.rsplit("v", 1)[0] if "v" in arxiv_id.split(".")[-1] else arxiv_id
            primary = entry.find("arxiv:primary_category", cls.NS)
            entries.append({
                "arxiv_id": base_id,
                "title": text("a:title"),
                "abstract": text("a:summary"),
                "authors": [" ".join(a.text.split()) for a in entry.findall("a:author/a:name", cls.NS) if a.text],
                "published": text("a:published")[:10],
                "updated": text("a:updated")[:10],
                "categories": [c.get("term") for c in entry.findall("a:category", cls.NS) if c.get("term")],
                "primary_category": primary.get("term") if primary is not None else None,
                "doi": text("arxiv:doi") or None,
                "journal_ref": text("arxiv:journal_ref") or None,
                "url": f"https://arxiv.org/abs/{base_id}",
            })
        return entries
