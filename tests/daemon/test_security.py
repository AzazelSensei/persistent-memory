import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token
from starlette.testclient import TestClient


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _token(tmp_path):
    return load_or_create_token(tmp_path)


def test_consolidate_requires_token(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "run_consolidation", lambda *, records_dir, cluster_only: {"ok": True})
    client = _client(tmp_path)
    resp = client.post("/api/consolidate")
    assert resp.status_code == 403


def test_consolidate_succeeds_with_token(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "run_consolidation", lambda *, records_dir, cluster_only: {"ok": True})
    client = _client(tmp_path)
    resp = client.post("/api/consolidate", headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_consolidate_rejects_wrong_token(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "run_consolidation", lambda *, records_dir, cluster_only: {"ok": True})
    client = _client(tmp_path)
    resp = client.post("/api/consolidate", headers={"X-PM-Token": "deadbeef"})
    assert resp.status_code == 403


def test_consolidate_is_post_only(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "run_consolidation", lambda *, records_dir, cluster_only: {})
    client = _client(tmp_path)
    assert client.get("/api/consolidate").status_code == 405


def test_accept_requires_token(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "apply_status", lambda rid, *, records_dir, status: {"id": rid, "status": status})
    client = _client(tmp_path)
    resp = client.post("/api/records/D-0007/accept")
    assert resp.status_code == 403


def test_accept_succeeds_with_token(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "apply_status", lambda rid, *, records_dir, status: {"id": rid, "status": status})
    client = _client(tmp_path)
    resp = client.post("/api/records/D-0007/accept", headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code == 200


def test_reject_requires_token(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "apply_status", lambda rid, *, records_dir, status: {"id": rid, "status": status})
    client = _client(tmp_path)
    resp = client.post("/api/records/L-0003/reject")
    assert resp.status_code == 403


def test_foreign_host_rejected(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert resp.status_code == 400


def test_localhost_host_allowed(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/health", headers={"Host": "localhost"})
    assert resp.status_code == 200


def test_dashboard_includes_token(tmp_path):
    client = _client(tmp_path)
    html = client.get("/legacy").text
    assert _token(tmp_path) in html
