"""Ingest jobs: fetch -> parse (thread pool) -> route to shards (sockets) -> rebuild -> notify.

Stages, as shown on the Ingest page:

1. *fetch*      uploaded files are already on disk; FTP files are downloaded in
                parallel; API imports page through OpenAlex / arXiv.
2. *parse*      a thread pool turns files into records (CSV, JSON, PDF, text...).
3. *distribute* every record is assigned to a shard with rendezvous hashing and
                sent in batches over TCP; the owner node runs the regex
                extraction and tokenisation, de-duplicates, stores and indexes.
4. *rebuild*    the global model and knowledge graph are refreshed cluster-wide.
5. *notify*     every node checks the new documents against its users' alerts.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..config import Settings
from ..p2p.cluster import Cluster, rendezvous_owner
from ..storage.app_store import AppStore
from .parsers import normalize_arxiv, normalize_openalex, parse_file
from .records import RawRecord
from .sources import ArxivClient, OpenAlexClient, ftp_download, ftp_expand

log = logging.getLogger(__name__)
BATCH_SIZE = 200
SAMPLE_FILE = "openalex_sample.jsonl.gz"


class IngestPipeline:
    def __init__(self, settings: Settings, cluster: Cluster, app: AppStore,
                 on_stored: Callable[[dict, list[dict]], dict]):
        self.settings = settings
        self.cluster = cluster
        self.app = app
        self.on_stored = on_stored  # rebuild + notify, supplied by the node
        self.jobs: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._last_save: dict[str, float] = {}
        self._runner = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest-job")
        self._parsers = ThreadPoolExecutor(max_workers=max(1, settings.ingest_workers), thread_name_prefix="parse")
        self._senders = ThreadPoolExecutor(max_workers=8, thread_name_prefix="route")

    # ------------------------------------------------------------------ job records

    def _new_job(self, kind: str, label: str, user: dict | None, files: list[dict] | None = None,
                 source: dict | None = None) -> dict:
        job = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "label": label,
            "status": "queued",
            "stage": "queued",
            "user_id": user["id"] if user else None,
            "user_name": user["name"] if user else "system",
            "node": self.settings.node_id,
            "source": source or {},
            "files": files or [],
            "totals": {"records": 0, "stored": 0, "duplicates": 0, "failed": 0},
            "per_node": {},
            "errors": [],
            "rebuild": None,
            "notified": None,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
        }
        with self._lock:
            self.jobs[job["id"]] = job
        self._save(job, force=True)
        return job

    def _save(self, job: dict, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_save.get(job["id"], 0) > 0.75:
            self._last_save[job["id"]] = now
            self.app.save_job(job)

    def _stage(self, job: dict, stage: str) -> None:
        job["stage"] = stage
        self._save(job, force=True)

    def _error(self, job: dict, message: str) -> None:
        job["errors"] = (job["errors"] + [message])[-50:]

    def job(self, job_id: str) -> dict | None:
        with self._lock:
            if job_id in self.jobs:
                return self.jobs[job_id]
        return self.app.job(job_id)

    def list_jobs(self, limit: int = 60) -> list[dict]:
        stored = {job["id"]: job for job in self.app.jobs(limit)}
        with self._lock:
            stored.update(self.jobs)
        return sorted(stored.values(), key=lambda j: -j["created_at"])[:limit]

    # ------------------------------------------------------------------ submitters

    def submit_files(self, files: list[tuple[Path, str]], user: dict | None, label: str | None = None) -> dict:
        entries = [{"name": name, "size": path.stat().st_size, "status": "waiting", "records": 0, "error": None}
                   for path, name in files]
        job = self._new_job("upload", label or (files[0][1] if len(files) == 1 else f"{len(files)} files"),
                            user, entries)
        self._runner.submit(self._run, job, lambda: files)
        return job

    def submit_sample(self, user: dict | None) -> dict:
        path = self.settings.samples_dir / SAMPLE_FILE
        if not path.exists():
            raise FileNotFoundError(f"bundled sample not found at {path}")
        job = self._new_job("sample", "OpenAlex sample corpus", user,
                            [{"name": SAMPLE_FILE, "size": path.stat().st_size, "status": "waiting", "records": 0,
                              "error": None}], {"path": str(path)})
        self._runner.submit(self._run, job, lambda: [(path, SAMPLE_FILE)])
        return job

    def submit_ftp(self, host: str, port: int, username: str, password: str, path: str, pattern: str,
                   user: dict | None) -> dict:
        source = {"host": host, "port": port, "user": username or "anonymous", "path": path, "pattern": pattern}
        job = self._new_job("ftp", f"ftp://{host}{path}", user, [], source)

        def fetch() -> list[tuple[Path, str]]:
            self._stage(job, "downloading")
            entries = ftp_expand(host, port, username, password, path, pattern or "*")
            if not entries:
                raise FileNotFoundError(f"no files match {pattern!r} under {path}")
            job["files"] = [{"name": e.name, "size": e.size, "status": "downloading", "records": 0, "error": None}
                            for e in entries]
            self._save(job, force=True)
            target = self.settings.uploads_dir / job["id"]
            by_name = {f["name"]: f for f in job["files"]}

            def downloaded(remote: str, local: Path | None, exc: Exception | None) -> None:
                entry = by_name.get(Path(remote).name)
                if entry:
                    entry["status"] = "downloaded" if exc is None else "failed"
                    entry["error"] = str(exc) if exc else None
                if exc:
                    self._error(job, f"{remote}: {exc}")
                self._save(job)

            local = ftp_download(host, port, username, password, [e.path for e in entries], target,
                                 workers=4, on_file=downloaded)
            return [(p, p.name) for p in local]

        self._runner.submit(self._run, job, fetch)
        return job

    def submit_remote(self, provider: str, query: str, limit: int, user: dict | None) -> dict:
        label = f"{'OpenAlex' if provider == 'openalex' else 'arXiv'}: {query}"
        job = self._new_job("remote", label, user, [], {"provider": provider, "query": query, "limit": limit})

        def fetch() -> list[RawRecord]:
            self._stage(job, "downloading")
            if provider == "openalex":
                client = OpenAlexClient(api_key=self.settings.openalex_api_key)
                works = list(client.iter_works(search=query, filter="has_abstract:true", limit=limit))
                records = [normalize_openalex(w) for w in works]
            else:
                entries = ArxivClient().search(query, max_results=limit)
                records = [normalize_arxiv(e) for e in entries]
            job["files"] = [{"name": label, "size": None, "status": "parsed", "records": len(records), "error": None}]
            return records

        self._runner.submit(self._run, job, fetch)
        return job

    # ------------------------------------------------------------------ running

    def _run(self, job: dict, fetch: Callable[[], list]) -> None:
        job["status"] = "running"
        job["started_at"] = time.time()
        self._save(job, force=True)
        try:
            fetched = fetch()
            if fetched and isinstance(fetched[0], RawRecord):
                records = fetched
            else:
                records = self._parse(job, fetched)
            job["totals"]["records"] = len(records)
            if not records:
                raise ValueError("no documents could be read from the input")
            stored_docs = self._distribute(job, records)
            if stored_docs:
                self._stage(job, "rebuilding")
                outcome = self.on_stored(job, stored_docs)
                job["rebuild"] = outcome.get("rebuild")
                job["notified"] = outcome.get("notified")
            job["status"] = "done" if job["totals"]["stored"] or job["totals"]["duplicates"] else "failed"
            if job["status"] == "failed" and not job["errors"]:
                self._error(job, "nothing was stored")
        except Exception as exc:  # noqa: BLE001 - surfaced on the job
            log.exception("ingest job %s failed", job["id"])
            job["status"] = "failed"
            self._error(job, f"{type(exc).__name__}: {exc}")
        finally:
            job["stage"] = "done"
            job["finished_at"] = time.time()
            self._save(job, force=True)
            if job["kind"] == "ftp":
                shutil.rmtree(self.settings.uploads_dir / job["id"], ignore_errors=True)

    def _parse(self, job: dict, files: list[tuple[Path, str]]) -> list[RawRecord]:
        """Parse files concurrently: one task per file on the parser thread pool."""
        self._stage(job, "parsing")
        by_name = {f["name"]: f for f in job["files"]}
        records: list[RawRecord] = []
        futures = {self._parsers.submit(parse_file, path, name): name for path, name in files}
        for future in as_completed(futures):
            name = futures[future]
            entry = by_name.setdefault(name, {"name": name, "size": None, "records": 0, "error": None})
            try:
                parsed = future.result()
                entry.update(status="parsed", records=len(parsed))
                records.extend(parsed)
                job["totals"]["records"] = len(records)
            except Exception as exc:  # noqa: BLE001 - per file
                entry.update(status="failed", error=str(exc))
                self._error(job, f"{name}: {exc}")
            self._save(job)
        if not job["files"]:
            job["files"] = list(by_name.values())
        return records

    def _distribute(self, job: dict, records: list[RawRecord]) -> list[dict]:
        """Rendezvous-hash every record to a live node and ship batches over TCP."""
        self._stage(job, "distributing")
        nodes = self.cluster.alive_nodes()
        groups: dict[str, list[RawRecord]] = defaultdict(list)
        for record in records:
            groups[rendezvous_owner(record.dedup_key(), nodes)].append(record)

        stored_docs: list[dict] = []
        per_node: Counter = Counter()
        lock = threading.Lock()

        def send(owner: str, batch: list[RawRecord]) -> None:
            payload = {"records": [r.to_dict() for r in batch], "job_id": job["id"], "via": self.settings.node_id}
            target = owner
            try:
                reply, _ = self.cluster.call(target, "STORE", payload, timeout=300)
            except Exception as exc:  # noqa: BLE001 - fall back to the next node in hash order
                remaining = [n for n in nodes if n != owner]
                if not remaining:
                    raise
                target = rendezvous_owner(batch[0].dedup_key(), remaining)
                log.warning("node %s failed (%s); sending batch to %s", owner, exc, target)
                with lock:
                    self._error(job, f"{owner} unreachable, {len(batch)} records re-routed to {target}")
                reply, _ = self.cluster.call(target, "STORE", payload, timeout=300)
            with lock:
                totals = job["totals"]
                totals["stored"] += reply["stored"]
                totals["duplicates"] += reply["duplicates"]
                totals["failed"] += len(reply["failed"])
                for failure in reply["failed"][:5]:
                    self._error(job, f"{failure['title']}: {failure['error']}")
                per_node[target] += reply["stored"]
                job["per_node"] = dict(per_node)
                stored_docs.extend(reply["documents"])
                self._save(job)

        futures = []
        for owner, items in groups.items():
            for i in range(0, len(items), BATCH_SIZE):
                futures.append(self._senders.submit(send, owner, items[i : i + BATCH_SIZE]))
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                self._error(job, f"batch failed: {exc}")
        return stored_docs
