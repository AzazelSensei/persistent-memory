import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token
from starlette.testclient import TestClient


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


class _FakeProc:
    def poll(self):
        return None


def test_metrics_endpoint_returns_counts(tmp_path):
    services.reset_metrics()
    client = _client(tmp_path)
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "prompt_recall_count" in body
    assert "extraction_started_count" in body
    assert "records_total" in body


def test_metrics_records_total_counts_markdown(tmp_path):
    services.reset_metrics()
    decisions = tmp_path / "decisions"
    lessons = tmp_path / "lessons"
    decisions.mkdir()
    lessons.mkdir()
    (decisions / "D-0001.md").write_text("x", encoding="utf-8")
    (lessons / "L-0001.md").write_text("x", encoding="utf-8")
    client = _client(tmp_path)
    body = client.get("/api/metrics").json()
    assert body["records_total"] == 2


def test_prompt_recall_bumps_metric(tmp_path):
    services.reset_metrics()
    services.run_prompt_recall("test sorgusu", records_dir=tmp_path, project=None)
    client = _client(tmp_path)
    body = client.get("/api/metrics").json()
    assert body["prompt_recall_count"] == 1


def test_extraction_started_bumps_metric(tmp_path, monkeypatch):
    services.reset_metrics()
    services.reset_extraction_state()
    monkeypatch.setattr(services.subprocess, "Popen", lambda *a, **k: _FakeProc())
    client = _client(tmp_path)
    token = load_or_create_token(tmp_path)
    payload = {"project": "abc123def456", "cwd": "/tmp/proj"}
    client.post("/api/extract", json=payload, headers={"X-PM-Token": token})
    body = client.get("/api/metrics").json()
    assert body["extraction_started_count"] == 1


def test_extraction_already_running_does_not_bump(tmp_path, monkeypatch):
    services.reset_metrics()
    services.reset_extraction_state()
    monkeypatch.setattr(services.subprocess, "Popen", lambda *a, **k: _FakeProc())
    client = _client(tmp_path)
    token = load_or_create_token(tmp_path)
    payload = {"project": "abc123def456", "cwd": "/tmp/proj"}
    headers = {"X-PM-Token": token}
    client.post("/api/extract", json=payload, headers=headers)
    client.post("/api/extract", json=payload, headers=headers)
    body = client.get("/api/metrics").json()
    assert body["extraction_started_count"] == 1
