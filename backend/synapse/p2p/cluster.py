"""Cluster membership, health checks, shard placement and parallel broadcast.

Every node is an equal peer. A node knows a few peer addresses from its
configuration and learns the rest by gossip: each PING reply lists the peers the
responder knows about, and a node that receives a PING from a stranger adds the
caller to its own list. Adding a fourth laptop therefore only needs one
existing address.

Shard placement uses rendezvous (highest-random-weight) hashing: a document
goes to the live node whose ``hash(node_id | key)`` is largest. Every node
computes the same answer without coordination, and when a node joins only about
1/n of new documents move to it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field

from .protocol import encode_json, parse_address, recv_frame, send_frame
from .server import Handler

log = logging.getLogger(__name__)

PING_INTERVAL = 5.0
DEAD_AFTER_FAILURES = 2


class PeerError(Exception):
    pass


@dataclass
class Peer:
    address: str
    node_id: str | None = None
    name: str | None = None
    alive: bool = False
    last_seen: float | None = None
    latency_ms: float | None = None
    failures: int = 0
    configured: bool = True
    info: dict = field(default_factory=dict)


@dataclass
class NodeResult:
    node_id: str
    ok: bool
    payload: dict = field(default_factory=dict)
    blob: bytes = b""
    error: str | None = None
    ms: float = 0.0
    address: str | None = None

    def summary(self) -> dict:
        return {"node": self.node_id, "ok": self.ok, "ms": round(self.ms, 1), "error": self.error}


def rendezvous_owner(key: str, nodes: Iterable[str]) -> str:
    """Highest-random-weight hashing: deterministic owner for ``key``."""
    def weight(node: str) -> int:
        return int.from_bytes(hashlib.blake2b(f"{node}|{key}".encode(), digest_size=8).digest(), "big")

    return max(nodes, key=weight)


def call_peer(address: str, kind: str, payload: dict | None = None, blob: bytes = b"", *,
              secret: bytes = b"", sender: str = "", timeout: float = 10.0) -> tuple[dict, bytes]:
    """One request/response over a fresh TCP connection."""
    host, port = parse_address(address)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        send_frame(sock, {"type": kind, "id": uuid.uuid4().hex[:12], "from": sender, "payload": payload or {}},
                   blob, secret)
        frame = recv_frame(sock, secret)
    if frame is None:
        raise PeerError(f"{address} closed the connection without replying")
    reply, reply_blob = frame
    if not reply.get("ok"):
        raise PeerError(reply.get("error") or "remote error")
    return reply.get("payload") or {}, reply_blob


class Cluster:
    def __init__(self, node_id: str, node_name: str, advertise: str, peers: Iterable[str],
                 secret: bytes, handlers: dict[str, Handler], local_info: Callable[[], dict]):
        self.node_id = node_id
        self.node_name = node_name
        self.advertise = advertise
        self.secret = secret
        self.handlers = handlers
        self.local_info = local_info
        self._lock = threading.RLock()
        self._peers: dict[str, Peer] = {}
        for address in peers:
            if address and address != advertise:
                self._peers[address] = Peer(address=address)
        self._pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="peer-call")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.membership_listeners: list[Callable[[str, str], None]] = []
        handlers["PING"] = self._handle_ping

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._thread = threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _heartbeat(self) -> None:
        while not self._stop.is_set():
            try:
                self.ping_all()
            except Exception:  # noqa: BLE001 - the heartbeat must survive anything
                log.exception("heartbeat failed")
            self._stop.wait(PING_INTERVAL)

    # ------------------------------------------------------------------ membership

    def _ping_payload(self) -> dict:
        return {"address": self.advertise, "node_id": self.node_id, "name": self.node_name}

    def _handle_ping(self, payload: dict, blob: bytes, sender: str | None) -> dict:
        address = payload.get("address")
        if address and address != self.advertise:
            with self._lock:
                peer = self._peers.get(address)
                if peer is None:
                    log.info("discovered peer %s (%s) via its ping", payload.get("node_id"), address)
                    peer = self._peers[address] = Peer(address=address, configured=False)
                was_alive = peer.alive
                peer.node_id = payload.get("node_id") or peer.node_id
                peer.name = payload.get("name") or peer.name
                peer.alive, peer.last_seen, peer.failures = True, time.time(), 0
            if not was_alive:
                self._notify("up", peer.node_id or address)
        return {
            **self.local_info(),
            "node_id": self.node_id,
            "name": self.node_name,
            "address": self.advertise,
            "peers": [p.address for p in self.peers() if p.alive] + [self.advertise],
        }

    def ping(self, peer: Peer) -> None:
        started = time.perf_counter()
        try:
            info, _ = call_peer(peer.address, "PING", self._ping_payload(), secret=self.secret,
                                sender=self.node_id, timeout=3.0)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                peer.failures += 1
                was_alive = peer.alive
                if peer.failures >= DEAD_AFTER_FAILURES:
                    peer.alive = False
                peer.info = {**peer.info, "error": str(exc)}
            if was_alive and not peer.alive:
                log.warning("peer %s (%s) is down: %s", peer.node_id, peer.address, exc)
                self._notify("down", peer.node_id or peer.address)
            return
        new_addresses = []
        with self._lock:
            was_alive = peer.alive
            if info.get("node_id") == self.node_id:  # we pinged ourselves under another name
                self._peers.pop(peer.address, None)
                return
            peer.node_id, peer.name = info.get("node_id"), info.get("name")
            peer.alive, peer.failures = True, 0
            peer.last_seen = time.time()
            peer.latency_ms = (time.perf_counter() - started) * 1000
            peer.info = {k: v for k, v in info.items() if k != "peers"}
            for address in info.get("peers", []):
                if address and address != self.advertise and address not in self._peers:
                    self._peers[address] = Peer(address=address, configured=False)
                    new_addresses.append(address)
        if not was_alive:
            log.info("peer %s (%s) is up, %.1f ms", peer.node_id, peer.address, peer.latency_ms)
            self._notify("up", peer.node_id or peer.address)
        for address in new_addresses:
            log.info("learned about peer %s by gossip", address)

    def ping_all(self) -> None:
        peers = self.peers()
        if peers:
            wait([self._pool.submit(self.ping, peer) for peer in peers], timeout=10)

    def _notify(self, event: str, node: str) -> None:
        for listener in self.membership_listeners:
            try:
                listener(event, node)
            except Exception:  # noqa: BLE001
                log.exception("membership listener failed")

    def add_peer(self, address: str) -> Peer:
        with self._lock:
            peer = self._peers.setdefault(address, Peer(address=address))
        self.ping(peer)
        return peer

    def peers(self) -> list[Peer]:
        with self._lock:
            return list(self._peers.values())

    def alive_nodes(self) -> list[str]:
        """Node ids of every reachable node, this one included."""
        with self._lock:
            ids = {p.node_id for p in self._peers.values() if p.alive and p.node_id}
        return sorted(ids | {self.node_id})

    def address_of(self, node_id: str) -> str | None:
        with self._lock:
            for peer in self._peers.values():
                if peer.node_id == node_id and peer.alive:
                    return peer.address
            for peer in self._peers.values():
                if peer.node_id == node_id:
                    return peer.address
        return None

    def wait_for_peers(self, timeout: float) -> list[str]:
        """Block until every configured peer answers (or ``timeout``)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ping_all()
            configured = [p for p in self.peers() if p.configured]
            if all(p.alive for p in configured):
                break
            time.sleep(1.0)
        return self.alive_nodes()

    def owner_for(self, key: str, nodes: list[str] | None = None) -> str:
        return rendezvous_owner(key, nodes or self.alive_nodes())

    def describe(self) -> list[dict]:
        local = {"node_id": self.node_id, "name": self.node_name, "address": self.advertise, "alive": True,
                 "self": True, "latency_ms": 0.0, "last_seen": time.time(), "info": self.local_info()}
        others = [{**asdict(p), "self": False} for p in self.peers()]
        return [local] + sorted(others, key=lambda p: p.get("node_id") or p["address"])

    # ------------------------------------------------------------------ RPC

    def call(self, node_id: str, kind: str, payload: dict | None = None, blob: bytes = b"",
             timeout: float = 15.0) -> tuple[dict, bytes]:
        """Call one node; the local node is called in-process, peers over TCP."""
        if node_id == self.node_id:
            # Round-trip through JSON so the local answer has exactly the shape a peer's
            # answer has after crossing the wire (string dict keys, lists not tuples).
            result = self.handlers[kind](json.loads(encode_json(payload or {})), blob, self.node_id)
            reply, reply_blob = result if isinstance(result, tuple) else (result, b"")
            return json.loads(encode_json(reply)), reply_blob
        address = self.address_of(node_id)
        if address is None:
            raise PeerError(f"node {node_id} is unknown or offline")
        try:
            return call_peer(address, kind, payload, blob, secret=self.secret, sender=self.node_id, timeout=timeout)
        except (OSError, ConnectionError) as exc:
            with self._lock:
                for peer in self._peers.values():
                    if peer.address == address:
                        peer.failures += 1
                        peer.alive = peer.failures < DEAD_AFTER_FAILURES and peer.alive
            raise PeerError(f"node {node_id} unreachable: {exc}") from exc

    def broadcast(self, kind: str, payload: dict | None = None, blob: bytes = b"", timeout: float = 20.0,
                  nodes: list[str] | None = None) -> dict[str, NodeResult]:
        """Send the same request to many nodes at once, one thread per node, and gather replies."""
        targets = nodes if nodes is not None else self.alive_nodes()

        def run(node: str) -> NodeResult:
            started = time.perf_counter()
            try:
                reply, reply_blob = self.call(node, kind, payload, blob, timeout=timeout)
                return NodeResult(node, True, reply, reply_blob, ms=(time.perf_counter() - started) * 1000)
            except Exception as exc:  # noqa: BLE001 - one failing peer must not fail the query
                return NodeResult(node, False, error=str(exc), ms=(time.perf_counter() - started) * 1000)

        futures = {node: self._pool.submit(run, node) for node in targets}
        done, _ = wait(futures.values(), timeout=timeout + 2)
        results = {}
        for node, future in futures.items():
            results[node] = future.result() if future in done else NodeResult(node, False, error="timed out", ms=timeout * 1000)
        return results
