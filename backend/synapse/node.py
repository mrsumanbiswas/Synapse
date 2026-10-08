"""A Synapse node: the composition root wiring storage, the shard engine, the P2P
layer and the application services together."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter

from . import __version__
from .config import Settings
from .ingest.pipeline import IngestPipeline
from .ingest.records import RawRecord
from .p2p.cluster import Cluster
from .p2p.server import Handler, PeerServer
from .services.auth import LoginThrottle, hash_password
from .services.coordinator import ModelCoordinator
from .services.notifier import Notifier
from .services.search import QueryEngine
from .services.shard import ShardEngine
from .storage.app_store import AppStore
from .storage.shard_store import ShardStore

log = logging.getLogger(__name__)
AUTO_REBUILD_COOLDOWN = 90.0
CONSISTENCY_INTERVAL = 20.0


class SynapseNode:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.started_at = time.time()
        self.shards = ShardStore(settings.shard_db_path)
        self.app = AppStore(settings.app_db_path)
        self.engine = ShardEngine(settings, self.shards)
        secret = settings.cluster_secret.encode()
        self.handlers: dict[str, Handler] = {}
        self.cluster = Cluster(settings.node_id, settings.node_name, settings.advertise, settings.peers, secret,
                               self.handlers, self.engine.info)
        self.peer_server = PeerServer(settings.peer_host, settings.peer_port, self.handlers, secret)
        self.coordinator = ModelCoordinator(settings, self.cluster, self.shards)
        self.search = QueryEngine(self.cluster, self.engine)
        self.notifier = Notifier(settings, self.app, self.engine)
        self.pipeline = IngestPipeline(settings, self.cluster, self.app, self._after_ingest)
        self.login_throttle = LoginThrottle()
        self._stop = threading.Event()
        self._last_auto_rebuild = 0.0
        self._register_handlers()

    # ------------------------------------------------------------------ RPC handlers

    def _register_handlers(self) -> None:
        engine, h = self.engine, self.handlers
        h["STATS"] = lambda p, b, s: engine.stats()
        h["STORE"] = lambda p, b, s: engine.store_records(
            [RawRecord.from_dict(r) for r in p["records"]], p.get("job_id"), p.get("via") or s)
        h["SEARCH"] = lambda p, b, s: engine.search(p)
        h["EXPLAIN"] = lambda p, b, s: engine.explain(p["query"])
        h["GET_DOC"] = lambda p, b, s: {"doc": engine.document(p["id"])}
        h["CARDS"] = lambda p, b, s: {"docs": engine.cards(p["ids"])}
        h["VECTOR_SEARCH"] = lambda p, b, s: engine.vector_search(p["vector"], int(p.get("k", 8)), p.get("exclude", []))
        h["POINTS"] = lambda p, b, s: {"points": engine.points(int(p.get("limit", 2000)))}
        h["RECENT"] = lambda p, b, s: {"docs": engine.store.recent(int(p.get("limit", 8)))}
        h["DELETE_DOC"] = lambda p, b, s: {"deleted": engine.delete(p["id"])}
        h["MODEL_STATS"] = lambda p, b, s: engine.model_stats()
        h["MODEL_SAMPLE"] = lambda p, b, s: engine.model_sample(int(p["limit"]), int(p.get("seed", 0)))
        h["MODEL_INSTALL"] = lambda p, b, s: engine.install_model(b)
        h["ANALYTICS_INSTALL"] = lambda p, b, s: engine.install_analytics(b)
        h["NEW_DOCS"] = lambda p, b, s: self.notifier.handle_new_documents(p.get("docs", []))
        h["TOP_QUERIES"] = lambda p, b, s: {"queries": self.app.popular_queries(int(p.get("limit", 10)))}

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self.engine.load()
        self.app.mark_interrupted_jobs()
        self._seed_admin()
        self.peer_server.start()
        self.cluster.membership_listeners.append(self._on_membership)
        self.cluster.start()
        threading.Thread(target=self._startup_tasks, name="startup", daemon=True).start()
        threading.Thread(target=self._consistency_loop, name="consistency", daemon=True).start()
        log.info("node %s (%s) ready; peers configured: %s", self.settings.node_id, self.settings.advertise,
                 ", ".join(self.settings.peers) or "none")

    def stop(self) -> None:
        self._stop.set()
        self.cluster.stop()
        self.peer_server.stop()
        self.shards.db.close()
        self.app.db.close()

    def _seed_admin(self) -> None:
        email, password = self.settings.admin_email, self.settings.admin_password
        if email and password and not self.app.user_with_secret(email):
            self.app.create_user(email, "Administrator", hash_password(password), "admin")
            log.info("created admin account %s", email)

    def _startup_tasks(self) -> None:
        if self.settings.peers:
            self.cluster.wait_for_peers(timeout=45)
        if self.settings.seed_sample and self._cluster_documents() == 0:
            log.info("cluster is empty: importing the bundled sample corpus")
            try:
                self.pipeline.submit_sample(None)
            except FileNotFoundError as exc:
                log.warning("cannot seed: %s", exc)
            return
        if self.engine.meta and self.engine.model is None:
            self._auto_rebuild("this node has documents but no model yet", force=True)

    def _cluster_documents(self) -> int:
        total = len(self.engine.meta)
        return total + sum(p.info.get("documents", 0) for p in self.cluster.peers() if p.alive)

    # ------------------------------------------------------------------ automatic rebuilds

    def _on_membership(self, event: str, node: str) -> None:
        log.info("membership: %s is %s", node, event)

    def _consistency_loop(self) -> None:
        """The lowest live node id re-syncs the model when nodes disagree on its version."""
        while not self._stop.wait(CONSISTENCY_INTERVAL):
            try:
                alive = self.cluster.alive_nodes()
                if alive[0] != self.settings.node_id or self.coordinator.running or self.pipeline_busy():
                    continue
                infos = [self.engine.info()] + [p.info for p in self.cluster.peers() if p.alive]
                documents = sum(i.get("documents", 0) for i in infos)
                versions = {i.get("model_version") for i in infos}
                if documents and (len(versions) > 1 or None in versions):
                    self._auto_rebuild(f"model versions differ across {len(alive)} nodes")
            except Exception:  # noqa: BLE001
                log.exception("consistency check failed")

    def pipeline_busy(self) -> bool:
        return any(j["status"] in ("queued", "running") for j in self.pipeline.jobs.values())

    def _auto_rebuild(self, reason: str, force: bool = False) -> None:
        if not force and time.time() - self._last_auto_rebuild < AUTO_REBUILD_COOLDOWN:
            return
        self._last_auto_rebuild = time.time()
        log.info("automatic rebuild: %s", reason)
        self.coordinator.rebuild_in_background(reason)

    def _after_ingest(self, job: dict, stored: list[dict]) -> dict:
        rebuild = self.coordinator.rebuild(f"ingest job {job['id']}")
        job["stage"] = "notifying"
        replies = self.cluster.broadcast("NEW_DOCS", {"docs": stored[:3000]}, timeout=30)
        notified = sum(r.payload.get("queued", 0) for r in replies.values() if r.ok)
        return {"rebuild": rebuild, "notified": notified}

    # ------------------------------------------------------------------ cluster views

    def cluster_status(self) -> dict:
        stats = self.cluster.broadcast("STATS", {}, timeout=6)
        nodes = []
        for entry in self.cluster.describe():
            node_id = entry.get("node_id")
            result = stats.get(node_id) if node_id else None
            nodes.append({**entry, "stats": result.payload if result and result.ok else None,
                          "error": result.error if result and not result.ok else entry.get("info", {}).get("error")})
        model = self.engine.model.info() if self.engine.model else None
        analytics = self.engine.analytics or {}
        return {
            "self": self.settings.node_id,
            "version": __version__,
            "uptime": time.time() - self.started_at,
            "nodes": nodes,
            "model": model,
            "analytics": {k: analytics.get(k) for k in ("version", "built_at", "leader", "graph_stats")} if analytics else None,
            "rebuilding": self.coordinator.running,
            "rebuilds": self.coordinator.history[:10],
            "secured": bool(self.settings.cluster_secret),
        }

    def popular_queries(self, limit: int = 8) -> list[dict]:
        replies = self.cluster.broadcast("TOP_QUERIES", {"limit": limit * 2}, timeout=5)
        counts: Counter = Counter()
        for result in replies.values():
            if result.ok:
                for item in result.payload["queries"]:
                    counts[item["query"]] += item["count"]
        return [{"query": q, "count": c} for q, c in counts.most_common(limit)]

    def recent_documents(self, limit: int = 6) -> list[dict]:
        replies = self.cluster.broadcast("RECENT", {"limit": limit}, timeout=5)
        docs = [d | {"node": n} for n, r in replies.items() if r.ok for d in r.payload["docs"]]
        docs.sort(key=lambda d: -(d.get("ingested_at") or 0))
        return docs[:limit]
