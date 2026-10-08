"""End-to-end test of one node through the HTTP API: sign-up, upload, search, graph."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PAPERS = Path(__file__).resolve().parents[2] / "infra" / "ftp" / "data" / "papers"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SYNAPSE_NODE_ID", "test-node")
    monkeypatch.setenv("SYNAPSE_PEER_HOST", "127.0.0.1")
    monkeypatch.setenv("SYNAPSE_PEER_PORT", "0")
    monkeypatch.setenv("SYNAPSE_LSA_DIMS", "3")
    from synapse.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _wait_for_job(client, headers, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/ingest/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.3)
    raise AssertionError("ingest job did not finish")


@pytest.mark.skipif(not PAPERS.exists(), reason="sample papers not available")
def test_ingest_search_and_explore(client):
    assert client.get("/api/health").json()["status"] == "ok"

    # The first account on a node without a configured admin becomes the admin.
    session = client.post("/api/auth/register", json={"email": "ada@example.org", "name": "Ada", "password": "correct horse"}).json()
    assert session["user"]["role"] == "admin"
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    assert client.post("/api/ingest/upload", files=[("files", ("x.txt", b"hi"))]).status_code == 401

    files = [("files", (p.name, p.read_bytes(), "text/plain")) for p in sorted(PAPERS.iterdir())]
    job = client.post("/api/ingest/upload", files=files, headers=headers).json()
    job = _wait_for_job(client, headers, job["id"])
    assert job["status"] == "done" and job["totals"]["stored"] == 4
    assert job["rebuild"]["status"] == "ok"

    result = client.get("/api/search", params={"q": "consistent hashing", "mode": "keyword"}).json()
    assert result["total"] >= 1
    top = result["results"][0]
    assert top["title"] == "Sharding a Search Index Across Peers Without a Coordinator"
    assert any(segment["h"] for segment in top["snippet"])

    boolean = client.get("/api/search", params={"q": "retrieval AND NOT peer", "mode": "boolean"}).json()
    assert all("Peers" not in r["title"] for r in boolean["results"])
    bad = client.get("/api/search", params={"q": "(retrieval AND", "mode": "boolean"})
    assert bad.status_code == 400

    explain = client.get("/api/search/explain", params={"q": "ranking NOT bursts"}).json()
    assert explain["rpn"] == ["ranking", "bursts", "NOT", "AND"]

    suggestions = client.get("/api/autocomplete", params={"q": "lat"}).json()["suggestions"]
    assert any(s["text"].startswith("lat") for s in suggestions)

    doc = client.get(f"/api/documents/{top['id']}").json()
    assert doc["entities"]["email"][0]["value"] == "priya.nair@synapse-demo.example.org"
    assert len(doc["references"]) == 7
    assert "@article{" in client.get(f"/api/documents/{top['id']}/bibtex").text

    cluster = client.get("/api/cluster").json()
    assert cluster["nodes"][0]["stats"]["documents"] == 4
    assert client.get("/api/analytics/overview").json()["documents"] == 4
