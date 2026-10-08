"""A threaded TCP server (``socketserver``) that answers RPC frames from peers."""

from __future__ import annotations

import logging
import socket
import socketserver
import threading
from collections.abc import Callable

from .protocol import ProtocolError, recv_frame, send_frame

log = logging.getLogger(__name__)

Handler = Callable[[dict, bytes, str | None], "dict | tuple[dict, bytes]"]
IDLE_TIMEOUT = 300.0


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class PeerServer:
    def __init__(self, host: str, port: int, handlers: dict[str, Handler], secret: bytes = b""):
        self.host, self.port = host, port
        self.handlers = handlers
        self.secret = secret
        self._server: _ThreadingServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def bound_port(self) -> int:
        return self._server.server_address[1] if self._server else self.port

    def start(self) -> None:
        outer = self

        class RequestHandler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                outer._serve_connection(self.request, self.client_address)

        self._server = _ThreadingServer((self.host, self.port), RequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="peer-server", daemon=True)
        self._thread.start()
        log.info("peer server listening on %s:%d", self.host, self.bound_port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _serve_connection(self, sock: socket.socket, client: tuple) -> None:
        sock.settimeout(IDLE_TIMEOUT)
        while True:
            try:
                frame = recv_frame(sock, self.secret)
            except ProtocolError as exc:
                log.warning("rejected frame from %s: %s", client[0], exc)
                return
            except (ConnectionError, TimeoutError, OSError):
                return
            if frame is None:
                return
            message, blob = frame
            kind = message.get("type", "")
            handler = self.handlers.get(kind)
            try:
                if handler is None:
                    raise ValueError(f"unknown message type {kind!r}")
                result = handler(message.get("payload") or {}, blob, message.get("from"))
                payload, out_blob = result if isinstance(result, tuple) else (result, b"")
                send_frame(sock, {"ok": True, "payload": payload}, out_blob, self.secret)
            except (ConnectionError, OSError):
                return
            except Exception as exc:  # noqa: BLE001 - errors travel back to the caller
                log.exception("handler %s failed", kind)
                try:
                    send_frame(sock, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, b"", self.secret)
                except OSError:
                    return
