"""TDD: POST /api/records with optional branch field."""

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


def test_create_record_without_branch_succeeds(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "No branch", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201


def test_create_record_with_branch_succeeds(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={
            "type": "decision",
            "title": "Has branch",
            "project": "BlackHoleLabs",
            "branch": "faz1-backend",
        },
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 201


def test_create_record_branch_stored_in_frontmatter(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={
            "type": "decision",
            "title": "Branch record",
            "project": "BlackHoleLabs",
            "branch": "faz1-backend",
        },
        headers=_headers(tmp_path),
    )
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["provenance"]["branch"] == "faz1-backend"


def test_create_record_no_branch_frontmatter_branch_is_none(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records",
        json={"type": "decision", "title": "NoBranch", "project": "myapp"},
        headers=_headers(tmp_path),
    )
    record_id = resp.json()["id"]
    path = tmp_path / "decisions" / f"{record_id}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1])
    # branch absent or null
    prov = fm.get("provenance", {})
    assert prov.get("branch") is None
