from datetime import date

from persistent_memory.lint import Severity, check_staleness, collect_records
from tests.test_collect_records import VALID_DECISION, write_record

TODAY = date(2026, 6, 2)


def rec(record_id="D-0001", d="2026-05-30", salience="0.8", status="accepted"):
    return (VALID_DECISION
            .replace("id: D-0001", f"id: {record_id}")
            .replace("date: 2026-01-10", f"date: {d}")
            .replace("salience: 0.8", f"salience: {salience}")
            .replace("status: accepted", f"status: {status}"))


def test_recent_high_salience_is_not_stale(tmp_path):
    write_record(tmp_path, "a.md", rec())
    assert check_staleness(collect_records(tmp_path), today=TODAY) == []


def test_old_and_low_salience_is_warning(tmp_path):
    write_record(tmp_path, "a.md", rec(d="2025-01-01", salience="0.1"))
    findings = check_staleness(collect_records(tmp_path), today=TODAY)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].check == "staleness"


def test_old_but_high_salience_is_not_stale(tmp_path):
    write_record(tmp_path, "a.md", rec(d="2025-01-01", salience="0.9"))
    assert check_staleness(collect_records(tmp_path), today=TODAY) == []


def test_superseded_record_is_never_stale(tmp_path):
    write_record(tmp_path, "a.md", rec(d="2025-01-01", salience="0.1", status="superseded"))
    assert check_staleness(collect_records(tmp_path), today=TODAY) == []
