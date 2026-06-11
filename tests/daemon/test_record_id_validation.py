import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token
from starlette.testclient import TestClient


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _headers(tmp_path):
    return {"X-PM-Token": load_or_create_token(tmp_path)}


def test_bad_prefix_not_500(tmp_path, monkeypatch):
    def fake_apply(rid, *, records_dir, status):
        raise KeyError(rid.split("-", 1)[0])

    monkeypatch.setattr(services, "apply_status", fake_apply)
    client = _client(tmp_path)
    resp = client.post("/api/records/X-0001/accept", headers=_headers(tmp_path))
    assert resp.status_code != 500
    assert 400 <= resp.status_code < 500


def test_short_id_not_500(tmp_path, monkeypatch):
    def fake_apply(rid, *, records_dir, status):
        raise ValueError(rid)

    monkeypatch.setattr(services, "apply_status", fake_apply)
    client = _client(tmp_path)
    resp = client.post("/api/records/D-00/accept", headers=_headers(tmp_path))
    assert resp.status_code != 500
    assert 400 <= resp.status_code < 500


def test_garbage_id_not_500(tmp_path, monkeypatch):
    def fake_apply(rid, *, records_dir, status):
        raise ValueError(rid)

    monkeypatch.setattr(services, "apply_status", fake_apply)
    client = _client(tmp_path)
    resp = client.post("/api/records/evil/reject", headers=_headers(tmp_path))
    assert resp.status_code != 500
    assert 400 <= resp.status_code < 500


def test_wellformed_nonexistent_is_404(tmp_path, monkeypatch):
    def fake_apply(rid, *, records_dir, status):
        raise FileNotFoundError(rid)

    monkeypatch.setattr(services, "apply_status", fake_apply)
    client = _client(tmp_path)
    resp = client.post("/api/records/D-9999/accept", headers=_headers(tmp_path))
    assert resp.status_code == 404


def test_search_top_k_zero_rejected(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/search", params={"q": "x", "top_k": 0})
    assert resp.status_code == 422


def test_search_top_k_huge_rejected(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/search", params={"q": "x", "top_k": 999999})
    assert resp.status_code == 422


def test_search_top_k_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "run_search", lambda q, *, records_dir, top_k: [])
    client = _client(tmp_path)
    resp = client.get("/api/search", params={"q": "x", "top_k": 10})
    assert resp.status_code == 200
