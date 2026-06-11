from starlette.testclient import TestClient

import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app


def test_search_page_renders_form(tmp_path):
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/search").text
    assert "<form" in html or 'id="q"' in html
    assert "/api/search" in html


def test_health_page_shows_lint(tmp_path, monkeypatch):
    def fake_run_lint(*, records_dir):
        return {"errors": [], "conflicts": ["D-0001 vs D-0002"]}

    monkeypatch.setattr(services, "run_lint", fake_run_lint)
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/health").text
    assert "D-0001 vs D-0002" in html


def test_graph_empty_state(tmp_path):
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/graph").text
    assert "graph" in html.lower()
    assert "not generated yet" in html.lower() or "iframe" in html.lower()


def test_graph_embeds_when_present(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.html").write_text("<html>GRAPH</html>", encoding="utf-8")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/graph").text
    assert "<iframe" in html
    assert "/static/graph/graph.html" in html
