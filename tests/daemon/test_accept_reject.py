from starlette.testclient import TestClient

import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _headers(tmp_path):
    return {"X-PM-Token": load_or_create_token(tmp_path)}


def test_accept_record(tmp_path, monkeypatch):
    calls = {}

    def fake_apply(record_id, *, records_dir, status):
        calls["id"] = record_id
        calls["status"] = status
        return {"id": record_id, "status": status}

    monkeypatch.setattr(services, "apply_status", fake_apply)
    client = _client(tmp_path)
    resp = client.post("/api/records/D-0007/accept", headers=_headers(tmp_path))
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert calls == {"id": "D-0007", "status": "accepted"}


def test_reject_record(tmp_path, monkeypatch):
    def fake_apply(record_id, *, records_dir, status):
        return {"id": record_id, "status": status}

    monkeypatch.setattr(services, "apply_status", fake_apply)
    client = _client(tmp_path)
    resp = client.post("/api/records/L-0003/reject", headers=_headers(tmp_path))
    assert resp.json()["status"] == "reverted-as-mistake"


def test_accept_unknown_returns_404(tmp_path, monkeypatch):
    def fake_apply(record_id, *, records_dir, status):
        raise FileNotFoundError(record_id)

    monkeypatch.setattr(services, "apply_status", fake_apply)
    client = _client(tmp_path)
    resp = client.post("/api/records/D-9999/accept", headers=_headers(tmp_path))
    assert resp.status_code == 404
