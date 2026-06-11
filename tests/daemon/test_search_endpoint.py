from starlette.testclient import TestClient

import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app


def test_search_returns_results(tmp_path, monkeypatch):
    def fake_run_search(query, *, records_dir, top_k):
        assert query == "N+1 sorgu"
        assert top_k == 5
        return [{"id": "D-0007", "score": 0.91, "title": "batch fetch"}]

    monkeypatch.setattr(services, "run_search", fake_run_search)
    client = TestClient(create_app(records_dir=tmp_path))
    body = client.get("/api/search", params={"q": "N+1 sorgu"}).json()
    assert body["results"][0]["id"] == "D-0007"
    assert body["query"] == "N+1 sorgu"


def test_search_requires_query(tmp_path):
    client = TestClient(create_app(records_dir=tmp_path))
    resp = client.get("/api/search")
    assert resp.status_code == 422


def test_search_respects_top_k(tmp_path, monkeypatch):
    captured = {}

    def fake_run_search(query, *, records_dir, top_k):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(services, "run_search", fake_run_search)
    client = TestClient(create_app(records_dir=tmp_path))
    client.get("/api/search", params={"q": "x", "top_k": 3})
    assert captured["top_k"] == 3
