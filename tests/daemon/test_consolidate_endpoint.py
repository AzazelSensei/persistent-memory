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


def test_consolidate_triggers_run(tmp_path, monkeypatch):
    calls = {}

    def fake_run(*, records_dir, cluster_only):
        calls["records_dir"] = str(records_dir)
        calls["cluster_only"] = cluster_only
        return {"communities": 3, "surprises": 2}

    monkeypatch.setattr(services, "run_consolidation", fake_run)
    client = _client(tmp_path)
    body = client.post("/api/consolidate", headers=_headers(tmp_path)).json()
    assert body["communities"] == 3
    assert calls["cluster_only"] is True


def test_consolidate_full_build_flag(tmp_path, monkeypatch):
    calls = {}

    def fake_run(*, records_dir, cluster_only):
        calls["cluster_only"] = cluster_only
        return {}

    monkeypatch.setattr(services, "run_consolidation", fake_run)
    client = _client(tmp_path)
    client.post("/api/consolidate", params={"full": "true"}, headers=_headers(tmp_path))
    assert calls["cluster_only"] is False
