"""Tests for POST /api/records — on-demand record creation endpoint."""

import yaml
from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _headers(tmp_path):
    return {"X-PM-Token": load_or_create_token(tmp_path)}


# ---------------------------------------------------------------------------
# 403 — no token
# ---------------------------------------------------------------------------

def test_create_record_requires_token(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "Use postgres", "body": "## Decision\n\nPostgres.", "project": "myapp"},
    )
    assert resp.status_code == 403


def test_create_record_wrong_token_returns_403(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "Use postgres", "body": "## Decision\n\nPostgres.", "project": "myapp"},
        headers={"X-PM-Token": "wrong-token"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 422 — invalid type
# ---------------------------------------------------------------------------

def test_create_record_invalid_type_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "principle", "title": "SOLID", "body": "Always apply.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "type" in detail.lower() or "decision" in detail.lower() or "lesson" in detail.lower()


def test_create_record_missing_title_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "body": "Something.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_create_record_missing_project_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "lesson", "title": "Some lesson", "body": "Body here."},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 201 — happy path: decision
# ---------------------------------------------------------------------------

def test_create_decision_returns_201(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "Use postgres", "body": "## Decision\n\nPostgres.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201


def test_create_decision_response_has_id_path_type(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "Use postgres", "body": "## Decision\n\nPostgres.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    data = resp.json()
    assert data["id"].startswith("D-")
    assert "decisions" in data["path"]
    assert data["type"] == "decision"


def test_create_decision_file_exists_on_disk(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "Use postgres", "body": "## Decision\n\nPostgres.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    assert path.exists()


def test_create_decision_frontmatter_parses(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "Use postgres", "body": "## Decision\n\nPostgres.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    # Parse frontmatter
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["id"] == record_id
    assert fm["type"] == "decision"
    assert fm["status"] == "proposed"
    assert fm["project"] == "myapp"


def test_create_decision_title_in_body(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "Use postgres", "body": "## Decision\n\nPostgres.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    assert "Use postgres" in text


# ---------------------------------------------------------------------------
# 201 — happy path: lesson
# ---------------------------------------------------------------------------

def test_create_lesson_returns_201(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "lesson", "title": "Always write tests first", "body": "## What happened\n\nBug.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201


def test_create_lesson_response_has_id_starting_with_L(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "lesson", "title": "Always write tests first", "body": "## What happened\n\nBug.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    data = resp.json()
    assert data["id"].startswith("L-")
    assert "lessons" in data["path"]
    assert data["type"] == "lesson"


def test_create_lesson_file_exists_on_disk(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "lesson", "title": "Always write tests first", "body": "## What happened\n\nBug.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    record_id = resp.json()["id"]
    path = tmp_path / "lessons" / f"{record_id}.md"
    assert path.exists()


def test_create_lesson_frontmatter_parses(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "lesson", "title": "Always write tests first", "body": "## What happened\n\nBug.", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    record_id = resp.json()["id"]
    path = tmp_path / "lessons" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["id"] == record_id
    assert fm["type"] == "lesson"
    assert fm["status"] == "proposed"
    assert fm["project"] == "myapp"


# ---------------------------------------------------------------------------
# ID allocation — sequential
# ---------------------------------------------------------------------------

def test_second_decision_gets_sequential_id(tmp_path):
    client = _client(tmp_path)
    headers = _headers(tmp_path)
    payload = {"type": "decision", "title": "First", "body": "body", "project": "p"}
    r1 = client.post("/api/records", json=payload, headers=headers)
    r2 = client.post("/api/records", json={**payload, "title": "Second"}, headers=headers)
    assert r1.json()["id"] == "D-0001"
    assert r2.json()["id"] == "D-0002"


def test_decision_and_lesson_ids_are_independent(tmp_path):
    client = _client(tmp_path)
    headers = _headers(tmp_path)
    rd = client.post("/api/records", json={"type": "decision", "title": "D", "body": "b", "project": "p"}, headers=headers)
    rl = client.post("/api/records", json={"type": "lesson", "title": "L", "body": "b", "project": "p"}, headers=headers)
    assert rd.json()["id"] == "D-0001"
    assert rl.json()["id"] == "L-0001"


# ---------------------------------------------------------------------------
# Optional fields: tags, salience
# ---------------------------------------------------------------------------

def test_create_decision_with_tags(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "T", "body": "b", "project": "p", "tags": ["db", "migration"]},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    assert "db" in fm["tags"]
    assert "migration" in fm["tags"]


def test_create_decision_with_salience(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "T", "body": "b", "project": "p", "salience": 0.9},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    assert abs(fm["salience"] - 0.9) < 1e-6


def test_create_decision_default_salience(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "T", "body": "b", "project": "p"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["salience"] == 0.5


# ---------------------------------------------------------------------------
# Optional provenance fields: session, cwd, agent
# ---------------------------------------------------------------------------

def test_create_decision_with_provenance(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={
            "type": "decision",
            "title": "T",
            "body": "b",
            "project": "p",
            "session": "sess-abc",
            "cwd": "/home/user/project",
            "agent": "codex",
        },
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["provenance"]["session"] == "sess-abc"
    assert fm["provenance"]["cwd"] == "/home/user/project"
    assert fm["provenance"]["agent"] == "codex"


def test_create_decision_without_body_uses_template(tmp_path):
    """When body is omitted, the decision template headings are used."""
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "T", "project": "p"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    assert "## Decision" in text
    assert "## Context / Problem" in text


def test_create_lesson_without_body_uses_template(tmp_path):
    """When body is omitted, the lesson template headings are used."""
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "lesson", "title": "T", "project": "p"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]
    path = tmp_path / "lessons" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    assert "## What happened" in text
    assert "## General rule" in text
