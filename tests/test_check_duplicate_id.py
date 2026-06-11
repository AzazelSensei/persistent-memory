from persistent_memory.lint import Severity, check_duplicate_id, collect_records
from tests.test_collect_records import VALID_DECISION, write_record


def test_unique_ids_produce_no_finding(tmp_path):
    write_record(tmp_path, "a.md", VALID_DECISION)
    write_record(tmp_path, "b.md", VALID_DECISION.replace("D-0001", "D-0002"))
    findings = check_duplicate_id(collect_records(tmp_path))
    assert findings == []


def test_duplicate_id_is_error_reported_once_per_dupe_id(tmp_path):
    write_record(tmp_path, "a.md", VALID_DECISION)
    write_record(tmp_path, "b.md", VALID_DECISION)
    findings = check_duplicate_id(collect_records(tmp_path))
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].record_id == "D-0001"
    assert findings[0].check == "duplicate-id"
