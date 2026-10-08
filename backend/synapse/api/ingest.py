"""Ingestion (curators and admins): uploads, FTP imports, API imports, the bundled sample."""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..ingest.parsers import is_supported
from ..ingest.sources import ftp_list
from .deps import Curator, NodeDep
from .schemas import FtpBody, RemoteBody

router = APIRouter(tags=["ingest"])
CHUNK = 1024 * 1024

FORMATS = [
    {"ext": ".csv / .tsv", "description": "One document per row; columns such as title, abstract, authors, year, doi"},
    {"ext": ".json / .jsonl", "description": "OpenAlex works, the arXiv Kaggle snapshot, or any list of objects"},
    {"ext": ".txt / .md / .tex", "description": "A raw paper: title, authors, abstract and references are found with regex"},
    {"ext": ".pdf", "description": "Text is extracted, then handled like a raw paper"},
    {"ext": ".html", "description": "Tags are stripped, then handled like a raw paper"},
    {"ext": ".xml / .atom", "description": "arXiv API feeds"},
    {"ext": ".zip / .tar / .gz", "description": "Archives of any of the above"},
]


def _safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", (name or "").replace("\\", "/").split("/")[-1]).strip(" .")
    return base[:120] or f"upload-{uuid.uuid4().hex[:6]}"


@router.get("/ingest/formats")
def formats():
    return {"formats": FORMATS}


@router.post("/ingest/upload", status_code=202)
async def upload(node: NodeDep, user: Curator, files: Annotated[list[UploadFile], File()],
                 label: Annotated[str | None, Form(max_length=120)] = None):
    """Upload one or more files; parsing and indexing continue in the background."""
    if not files:
        raise HTTPException(400, "Choose at least one file")
    rejected = [f.filename for f in files if not is_supported(f.filename or "")]
    if rejected:
        raise HTTPException(415, f"Unsupported file type: {', '.join(map(str, rejected))}")
    limit = node.settings.max_upload_mb * 1024 * 1024
    target = node.settings.uploads_dir / uuid.uuid4().hex[:12]
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    for upload_file in files:
        name = _safe_name(upload_file.filename or "")
        path = target / name
        counter = 1
        while path.exists():
            path = target / f"{counter}-{name}"
            counter += 1
        size = 0
        with open(path, "wb") as fh:
            while chunk := await upload_file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"{name} is larger than {node.settings.max_upload_mb} MB")
                fh.write(chunk)
        saved.append((path, name))
    return node.pipeline.submit_files(saved, user, label)


@router.post("/ingest/ftp/browse")
async def ftp_browse(body: FtpBody, user: Curator):
    """List a remote FTP directory before importing from it."""
    try:
        entries = await run_in_threadpool(ftp_list, body.host, body.port, body.username, body.password, body.path or "/")
    except Exception as exc:  # noqa: BLE001 - network errors are shown in the dialog
        raise HTTPException(502, f"FTP error: {exc}") from exc
    return {"path": body.path or "/", "entries": [vars(e) | {"supported": e.is_dir or is_supported(e.name)}
                                                  for e in entries]}


@router.post("/ingest/ftp", status_code=202)
def ftp_import(body: FtpBody, node: NodeDep, user: Curator):
    return node.pipeline.submit_ftp(body.host, body.port, body.username, body.password, body.path or "/",
                                    body.pattern or "*", user)


@router.post("/ingest/remote", status_code=202)
def remote_import(body: RemoteBody, node: NodeDep, user: Curator):
    return node.pipeline.submit_remote(body.provider, body.query, body.limit, user)


@router.post("/ingest/sample", status_code=202)
def sample_import(node: NodeDep, user: Curator):
    try:
        return node.pipeline.submit_sample(user)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/ingest/jobs")
def jobs(node: NodeDep, user: Curator):
    return {"jobs": node.pipeline.list_jobs()}


@router.get("/ingest/jobs/{job_id}")
def job(job_id: str, node: NodeDep, user: Curator):
    found = node.pipeline.job(job_id)
    if not found:
        raise HTTPException(404, "Job not found")
    return found
