"""Wire protocol for peer-to-peer RPC over plain TCP sockets.

Every message is one frame::

    +--------+------------+-----------+-------------+--------------+-----------+
    | "SYN1" | header len | blob len  | HMAC-SHA256 | JSON header  | blob      |
    | 4 B    | uint32 BE  | uint32 BE | 32 B        | (header len) | (blob len)|
    +--------+------------+-----------+-------------+--------------+-----------+

Requests carry ``{"type", "id", "from", "payload"}`` and replies
``{"ok", "payload"}`` or ``{"ok": false, "error"}``. The optional binary blob
moves bulky data (the compressed global model) without JSON overhead. When a
cluster secret is configured the HMAC authenticates every frame, so a stranger
on the LAN cannot inject documents or models.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import struct

import numpy as np

MAGIC = b"SYN1"
PREFIX = struct.Struct("!4sII32s")
MAX_HEADER_BYTES = 128 * 1024 * 1024
MAX_BLOB_BYTES = 1024 * 1024 * 1024
NO_SIGNATURE = b"\x00" * 32


class ProtocolError(Exception):
    pass


def _default(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def encode_json(message: dict) -> bytes:
    return json.dumps(message, separators=(",", ":"), default=_default, ensure_ascii=False).encode()


def signature(secret: bytes, header: bytes, blob: bytes) -> bytes:
    if not secret:
        return NO_SIGNATURE
    mac = hmac.new(secret, header, hashlib.sha256)
    mac.update(blob)
    return mac.digest()


def send_frame(sock: socket.socket, message: dict, blob: bytes = b"", secret: bytes = b"") -> None:
    header = encode_json(message)
    sock.sendall(PREFIX.pack(MAGIC, len(header), len(blob), signature(secret, header, blob)) + header)
    if blob:
        sock.sendall(blob)


def _recv_exact(sock: socket.socket, size: int, allow_eof: bool = False) -> bytes | None:
    buffer = bytearray(size)
    view = memoryview(buffer)
    received = 0
    while received < size:
        count = sock.recv_into(view[received:], size - received)
        if count == 0:
            if allow_eof and received == 0:
                return None
            raise ConnectionError("peer closed the connection mid-frame")
        received += count
    return bytes(buffer)


def recv_frame(sock: socket.socket, secret: bytes = b"") -> tuple[dict, bytes] | None:
    """Read one frame; ``None`` on a clean end of stream."""
    prefix = _recv_exact(sock, PREFIX.size, allow_eof=True)
    if prefix is None:
        return None
    magic, header_len, blob_len, mac = PREFIX.unpack(prefix)
    if magic != MAGIC:
        raise ProtocolError("not a Synapse peer (bad magic bytes)")
    if header_len > MAX_HEADER_BYTES or blob_len > MAX_BLOB_BYTES:
        raise ProtocolError("frame too large")
    header = _recv_exact(sock, header_len) or b""
    blob = _recv_exact(sock, blob_len) if blob_len else b""
    if secret and not hmac.compare_digest(mac, signature(secret, header, blob or b"")):
        raise ProtocolError("bad frame signature (cluster secrets differ?)")
    return json.loads(header), blob or b""


def parse_address(address: str, default_port: int = 7000) -> tuple[str, int]:
    host, _, port = address.rpartition(":")
    if not host:
        return address, default_port
    return host.strip("[]"), int(port)
