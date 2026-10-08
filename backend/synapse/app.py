"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api import analytics, auth, cluster, documents, ingest, search
from .config import Settings
from .index.query_parser import QuerySyntaxError
from .node import SynapseNode
from .p2p.cluster import PeerError

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        node = SynapseNode(settings)
        app.state.node = node
        await run_in_threadpool(node.start)
        try:
            yield
        finally:
            await run_in_threadpool(node.stop)

    app = FastAPI(
        title="Synapse",
        version=__version__,
        description="A distributed knowledge graph and semantic search engine.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(QuerySyntaxError)
    async def query_syntax(_: Request, exc: QuerySyntaxError):
        return JSONResponse({"detail": str(exc), "position": exc.position}, status_code=400)

    @app.exception_handler(PeerError)
    async def peer_error(_: Request, exc: PeerError):
        return JSONResponse({"detail": f"A peer node could not be reached: {exc}"}, status_code=503)

    for module in (search, documents, analytics, auth, ingest, cluster):
        app.include_router(module.router, prefix="/api")
    return app
