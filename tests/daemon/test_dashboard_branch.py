"""Tests for branch field propagation through dashboard_data and detail endpoint."""

import json

from starlette.testclient import TestClient

from persistent_memory.daemon import dashboard_data
from persistent_memory.daemon.app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_record(directory, rec_id, rec_type, *, branch=None, project="myproj"):
    directory.mkdir(parents=True, exist_ok=True)
    branch_line = f"\n  branch: {branch}" if branch else ""
    front = (
        f"---\n"
        f"id: {rec_id}\n"
        f"type: {rec_type}\n"
        f"status: proposed\n"
        f"date: '2026-06-11'\n"
        f"project: {project}\n"
        f"provenance:\n"
        f"  session: s-1\n"
        f"  cwd: /tmp/work\n"
        f"  agent: claude-sonnet-4-6{branch_line}\n"
        f"tags: []\n"
        f"supersedes: []\n"
        f"superseded-by: []\n"
        f"salience: 0.5\n"
        f"---\n"
    )
    body = f"# Title for {rec_id}\n\n## Context\nsome text\n"
    (directory / f"{rec_id}.md").write_text(front + body, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. _build_record includes branch when provenance.branch is set
# ---------------------------------------------------------------------------

def test_build_record_includes_branch_when_set(tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision", branch="feat/i18n")
    from persistent_memory.records import read_record

    path = tmp_path / "decisions" / "D-0001.md"
    record, body = read_record(path)
    assert record.provenance.branch == "feat/i18n"

    result = dashboard_data._build_record(record, body, "Title for D-0001")
    assert result["branch"] == "feat/i18n"


def test_build_record_branch_is_none_when_absent(tmp_path):
    _write_record(tmp_path / "decisions", "D-0002", "decision", branch=None)
    from persistent_memory.records import read_record

    path = tmp_path / "decisions" / "D-0002.md"
    record, body = read_record(path)
    assert record.provenance.branch is None

    result = dashboard_data._build_record(record, body, "Title for D-0002")
    assert result.get("branch") is None


# ---------------------------------------------------------------------------
# 2. pm_payload JSON round-trips branch
# ---------------------------------------------------------------------------

def test_pm_payload_json_contains_branch(tmp_path):
    _write_record(tmp_path / "decisions", "D-0003", "decision", branch="main")
    from persistent_memory.daemon.config import DaemonConfig

    cfg = DaemonConfig(records_dir=tmp_path)
    raw = dashboard_data.pm_payload_json(cfg)
    data = json.loads(raw)
    decision = next(r for r in data["decisions"] if r["id"] == "D-0003")
    assert decision["branch"] == "main"


def test_pm_payload_json_no_branch_field_is_none(tmp_path):
    _write_record(tmp_path / "decisions", "D-0004", "decision", branch=None)
    from persistent_memory.daemon.config import DaemonConfig

    cfg = DaemonConfig(records_dir=tmp_path)
    raw = dashboard_data.pm_payload_json(cfg)
    data = json.loads(raw)
    decision = next(r for r in data["decisions"] if r["id"] == "D-0004")
    assert decision.get("branch") is None


# ---------------------------------------------------------------------------
# 3. /api/records/{id}/detail-equivalent: provenance in record_detail has branch
# ---------------------------------------------------------------------------

def test_record_detail_service_provenance_includes_branch(tmp_path):
    _write_record(tmp_path / "decisions", "D-0005", "decision", branch="hotfix/typo")
    from persistent_memory.daemon import services

    detail = services.record_detail(tmp_path, "D-0005")
    assert detail["provenance"]["branch"] == "hotfix/typo"


def test_record_detail_service_provenance_branch_absent_is_none(tmp_path):
    _write_record(tmp_path / "decisions", "D-0006", "decision", branch=None)
    from persistent_memory.daemon import services

    detail = services.record_detail(tmp_path, "D-0006")
    assert detail["provenance"].get("branch") is None


# ---------------------------------------------------------------------------
# 4. SPA detail view: JSX source contains branch chip logic
# ---------------------------------------------------------------------------

def test_views_detail_jsx_references_branch():
    from pathlib import Path

    jsx = Path(__file__).parent.parent.parent / (
        "src/persistent_memory/daemon/static/pm/views-detail.jsx"
    )
    source = jsx.read_text(encoding="utf-8")
    assert "rec.branch" in source, "views-detail.jsx must reference rec.branch"
