import json

import pytest
from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig


def _line(**kw):
    return json.dumps(kw)


def _user(cwd, text, ts):
    return _line(type="user", cwd=cwd, timestamp=ts,
                 message={"role": "user", "content": text})


def _assistant(cwd, text, ts):
    return _line(type="assistant", cwd=cwd, timestamp=ts,
                 message={"role": "assistant", "content": [{"type": "text", "text": text}]})


def _write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def app_with_transcripts(tmp_path):
    root = tmp_path / "projects"
    alpha_cwd = "/Users/dev/Desktop/alpha"
    _write_jsonl(root / "-Users-dev-Desktop-alpha" / "s1.jsonl", [
        _user(alpha_cwd, "Postgres secildi", "2026-06-01T10:00:00.000Z"),
        _assistant(alpha_cwd, "tamam", "2026-06-01T10:00:05.000Z"),
    ])
    beta_cwd = "/Users/dev/Desktop/beta"
    _write_jsonl(root / "-Users-dev-Desktop-beta" / "s2.jsonl", [
        _user(beta_cwd, "Playwright dersi", "2026-06-03T12:00:00.000Z"),
        _assistant(beta_cwd, "ok", "2026-06-03T12:00:05.000Z"),
    ])
    cfg = DaemonConfig(records_dir=tmp_path, projects_root=root, watch_enabled=False)
    return create_app(records_dir=tmp_path, config=cfg)


def test_api_projects_returns_overview(app_with_transcripts):
    client = TestClient(app_with_transcripts)
    data = client.get("/api/projects").json()
    names = [p["name"] for p in data["projects"]]
    assert names == ["beta", "alpha"]
    alpha = next(p for p in data["projects"] if p["name"] == "alpha")
    assert alpha["transcript_count"] == 1


def test_api_projects_no_token_needed(app_with_transcripts):
    client = TestClient(app_with_transcripts)
    assert client.get("/api/projects").status_code == 200


def test_api_project_detail(app_with_transcripts):
    client = TestClient(app_with_transcripts)
    data = client.get("/api/projects/alpha").json()
    assert data["name"] == "alpha"
    texts = [m["text"] for m in data["recent_messages"]]
    assert "Postgres secildi" in texts


def test_api_project_detail_unknown_empty(app_with_transcripts):
    client = TestClient(app_with_transcripts)
    data = client.get("/api/projects/nonexistent").json()
    assert data["name"] == "nonexistent"
    assert data["recent_messages"] == []


def test_projects_page_renders_cards(app_with_transcripts):
    client = TestClient(app_with_transcripts)
    html = client.get("/projects").text
    assert "alpha" in html
    assert "beta" in html
    assert "/projects/alpha" in html


def test_projects_page_in_nav(app_with_transcripts):
    client = TestClient(app_with_transcripts)
    html = client.get("/legacy").text
    assert "Projects" in html
    assert "/projects" in html


def test_project_detail_page_renders(app_with_transcripts):
    client = TestClient(app_with_transcripts)
    html = client.get("/projects/alpha").text
    assert "alpha" in html
    assert "Postgres secildi" in html


def test_projects_page_escapes_xss(tmp_path):
    root = tmp_path / "projects"
    evil_cwd = "/Users/dev/Desktop/<script>alert(1)</script>"
    _write_jsonl(root / "-Users-dev-Desktop-evil" / "s.jsonl", [
        _user(evil_cwd, "<img src=x onerror=alert(2)>", "2026-06-01T10:00:00.000Z"),
    ])
    cfg = DaemonConfig(records_dir=tmp_path, projects_root=root, watch_enabled=False)
    client = TestClient(create_app(records_dir=tmp_path, config=cfg))
    html = client.get("/projects").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
