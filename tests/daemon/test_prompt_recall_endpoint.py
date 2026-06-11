from starlette.testclient import TestClient

import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def test_prompt_recall_returns_block(tmp_path, monkeypatch):
    captured = {}

    def fake_run_prompt_recall(query, *, records_dir, project, budget):
        captured.update(query=query, project=project, budget=budget)
        return "📌 Relevant past memory:\n- [D-0007] batch fetch (alpha): single JOIN"

    monkeypatch.setattr(services, "run_prompt_recall", fake_run_prompt_recall)
    body = _client(tmp_path).get(
        "/api/prompt-recall", params={"q": "N+1 query", "project": "alpha"}
    ).json()
    assert "D-0007" in body["block"]
    assert captured["query"] == "N+1 query"
    assert captured["project"] == "alpha"


def test_prompt_recall_requires_query(tmp_path):
    resp = _client(tmp_path).get("/api/prompt-recall", params={"project": "alpha"})
    assert resp.status_code == 422


def test_prompt_recall_no_token_required(tmp_path, monkeypatch):
    monkeypatch.setattr(
        services, "run_prompt_recall", lambda q, *, records_dir, project, budget: ""
    )
    resp = _client(tmp_path).get("/api/prompt-recall", params={"q": "x", "project": "p"})
    assert resp.status_code == 200


def test_prompt_recall_passes_custom_budget(tmp_path, monkeypatch):
    captured = {}

    def fake(query, *, records_dir, project, budget):
        captured["budget"] = budget
        return ""

    monkeypatch.setattr(services, "run_prompt_recall", fake)
    _client(tmp_path).get(
        "/api/prompt-recall", params={"q": "x", "project": "p", "budget": 300}
    )
    assert captured["budget"] == 300


def test_prompt_recall_empty_block_when_service_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        services, "run_prompt_recall", lambda q, *, records_dir, project, budget: ""
    )
    body = _client(tmp_path).get(
        "/api/prompt-recall", params={"q": "x", "project": "p"}
    ).json()
    assert body["block"] == ""


def test_prompt_recall_never_errors_when_service_raises(tmp_path, monkeypatch):
    def boom(query, *, records_dir, project, budget):
        raise RuntimeError("index missing")

    monkeypatch.setattr(services, "run_prompt_recall", boom)
    resp = _client(tmp_path).get("/api/prompt-recall", params={"q": "x", "project": "p"})
    assert resp.status_code == 200
    assert resp.json()["block"] == ""
