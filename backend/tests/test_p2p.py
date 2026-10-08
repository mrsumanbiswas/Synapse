import socket
from collections import Counter

import pytest

from synapse.p2p.cluster import PeerError, call_peer, rendezvous_owner
from synapse.p2p.protocol import ProtocolError, recv_frame, send_frame
from synapse.p2p.server import PeerServer


def test_frames_round_trip_with_blob_and_signature():
    a, b = socket.socketpair()
    with a, b:
        send_frame(a, {"type": "X", "payload": {"n": 1}}, b"\x00\x01binary", secret=b"s3cret")
        message, blob = recv_frame(b, secret=b"s3cret")
        assert message == {"type": "X", "payload": {"n": 1}}
        assert blob == b"\x00\x01binary"

        send_frame(a, {"type": "Y"}, secret=b"s3cret")
        with pytest.raises(ProtocolError):
            recv_frame(b, secret=b"other-secret")


def test_clean_end_of_stream():
    a, b = socket.socketpair()
    with b:
        a.close()
        assert recv_frame(b) is None


def test_rendezvous_hashing_is_balanced_and_stable():
    keys = [f"doi:10.1/{i}" for i in range(3000)]
    three = {k: rendezvous_owner(k, ["node-a", "node-b", "node-c"]) for k in keys}
    counts = Counter(three.values())
    assert all(800 < c < 1200 for c in counts.values())

    four = {k: rendezvous_owner(k, ["node-a", "node-b", "node-c", "node-d"]) for k in keys}
    moved = [k for k in keys if three[k] != four[k]]
    assert all(four[k] == "node-d" for k in moved)  # keys only ever move to the new node
    assert 550 < len(moved) < 950  # about a quarter


def test_peer_server_answers_and_reports_errors():
    def echo(payload, blob, sender):
        return {"echo": payload, "from": sender}, blob[::-1]

    def boom(payload, blob, sender):
        raise RuntimeError("bad things")

    server = PeerServer("127.0.0.1", 0, {"ECHO": echo, "BOOM": boom}, secret=b"k")
    server.start()
    try:
        address = f"127.0.0.1:{server.bound_port}"
        reply, blob = call_peer(address, "ECHO", {"x": [1, 2]}, b"abc", secret=b"k", sender="tester")
        assert reply == {"echo": {"x": [1, 2]}, "from": "tester"} and blob == b"cba"
        with pytest.raises(PeerError, match="bad things"):
            call_peer(address, "BOOM", secret=b"k")
        with pytest.raises(PeerError, match="unknown message type"):
            call_peer(address, "NOPE", secret=b"k")
    finally:
        server.stop()
