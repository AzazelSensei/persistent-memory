"""Payload-shape contract for build_pm_payload: no duplicate record copies,
no embedded section bodies, and a byte-size budget so /app stays light."""

import json
import textwrap

from persistent_memory.daemon import dashboard_data
from persistent_memory.daemon.config import DaemonConfig

RECORD_COUNT_FOR_BUDGET = 300
MAX_BYTES_PER_RECORD = 900


def _write_record(directory, rec_id, rec_type, *, date="2026-06-11", project="alpha"):
    directory.mkdir(parents=True, exist_ok=True)
    front = textwrap.dedent(f"""\
        ---
        id: {rec_id}
        type: {rec_type}
        status: proposed
        date: '{date}'
        project: {project}
        provenance:
          session: s-1
          cwd: /tmp/work
          agent: claude-sonnet-4-6
        tags: []
        supersedes: []
        superseded-by: []
        salience: 0.5
        ---
        """)
    body = (
        f"# Title for {rec_id}\n\n"
        "## Context\n" + ("context text " * 20) + "\n\n"
        "## Decision\n" + ("decision text " * 20) + "\n\n"
        "## Rationale\n" + ("rationale text " * 20) + "\n\n"
        "## Outcome\n" + ("outcome text " * 20) + "\n"
    )
    (directory / f"{rec_id}.md").write_text(front + body, encoding="utf-8")


def _cfg(tmp_path):
    return DaemonConfig(records_dir=tmp_path, projects_root=tmp_path)


def test_payload_has_no_byid_field(tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision")
    payload = dashboard_data.build_pm_payload(_cfg(tmp_path))
    assert "byId" not in payload


def test_payload_has_no_decisions_field(tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision")
    payload = dashboard_data.build_pm_payload(_cfg(tmp_path))
    assert "decisions" not in payload


def test_payload_has_no_lessons_field(tmp_path):
    _write_record(tmp_path / "lessons", "L-0001", "lesson")
    payload = dashboard_data.build_pm_payload(_cfg(tmp_path))
    assert "lessons" not in payload


def test_payload_all_still_contains_every_record(tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision")
    _write_record(tmp_path / "lessons", "L-0001", "lesson")
    payload = dashboard_data.build_pm_payload(_cfg(tmp_path))
    ids = {r["id"] for r in payload["all"]}
    assert ids == {"D-0001", "L-0001"}


def test_records_in_all_have_no_sections_field(tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision")
    _write_record(tmp_path / "lessons", "L-0001", "lesson")
    payload = dashboard_data.build_pm_payload(_cfg(tmp_path))
    for record in payload["all"]:
        assert "sections" not in record


def test_pm_payload_json_stays_under_size_budget_for_representative_corpus(tmp_path):
    for i in range(RECORD_COUNT_FOR_BUDGET):
        rec_id = f"D-{i:04d}"
        _write_record(tmp_path / "decisions", rec_id, "decision", date="2026-06-11")

    raw = dashboard_data.pm_payload_json(_cfg(tmp_path))
    size_bytes = len(raw.encode("utf-8"))
    budget = RECORD_COUNT_FOR_BUDGET * MAX_BYTES_PER_RECORD
    assert size_bytes < budget, (
        f"payload {size_bytes} bytes exceeds budget {budget} bytes "
        f"for {RECORD_COUNT_FOR_BUDGET} records"
    )
    data = json.loads(raw)
    assert "byId" not in data
    assert "decisions" not in data
    assert "lessons" not in data
