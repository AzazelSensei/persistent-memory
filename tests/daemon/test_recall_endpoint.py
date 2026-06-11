from starlette.testclient import TestClient

import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def test_recall_returns_block(tmp_path, monkeypatch):
    def fake_run_recall(*, records_dir, project):
        assert project == "pk1"
        return "## Recall — past decisions and lessons\n- [D-0007] batch fetch (accepted, 2026-06-01)"

    monkeypatch.setattr(services, "run_recall", fake_run_recall)
    body = _client(tmp_path).get("/api/recall", params={"project": "pk1"}).json()
    assert "D-0007" in body["block"]


def test_recall_passes_none_project_when_absent(tmp_path, monkeypatch):
    captured = {}

    def fake_run_recall(*, records_dir, project):
        captured["project"] = project
        return ""

    monkeypatch.setattr(services, "run_recall", fake_run_recall)
    body = _client(tmp_path).get("/api/recall").json()
    assert captured["project"] is None
    assert body["block"] == ""


def test_recall_is_readonly_no_token_required(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "run_recall", lambda *, records_dir, project: "")
    resp = _client(tmp_path).get("/api/recall", params={"project": "pk1"})
    assert resp.status_code == 200
