from persistent_memory.lint import Severity, check_supersession, collect_records
from tests.test_collect_records import VALID_DECISION, write_record


def make_old(superseded_by="[D-0002]", status="superseded"):
    return (VALID_DECISION
            .replace("status: accepted", f"status: {status}")
            .replace("superseded-by: []", f"superseded-by: {superseded_by}"))


def make_new(supersedes="[D-0001]"):
    return (VALID_DECISION
            .replace("id: D-0001", "id: D-0002")
            .replace("supersedes: []", f"supersedes: {supersedes}"))


def test_consistent_bidirectional_chain_is_clean(tmp_path):
    write_record(tmp_path, "old.md", make_old())
    write_record(tmp_path, "new.md", make_new())
    findings = check_supersession(collect_records(tmp_path))
    assert findings == []


def test_superseded_by_missing_target_is_error(tmp_path):
    write_record(tmp_path, "old.md", make_old(superseded_by="[D-9999]"))
    findings = check_supersession(collect_records(tmp_path))
    checks = {(f.check, f.severity) for f in findings}
    assert ("supersession", Severity.ERROR) in checks


def test_missing_back_reference_is_error(tmp_path):
    write_record(tmp_path, "old.md", make_old())
    write_record(tmp_path, "new.md", make_new(supersedes="[]"))
    findings = check_supersession(collect_records(tmp_path))
    assert any(f.severity is Severity.ERROR for f in findings)
    assert any("bidirectional link inconsistent" in f.message for f in findings)


def test_superseded_by_but_status_still_accepted_is_warning(tmp_path):
    write_record(tmp_path, "old.md", make_old(status="accepted"))
    write_record(tmp_path, "new.md", make_new())
    findings = check_supersession(collect_records(tmp_path))
    assert any(f.severity is Severity.WARNING for f in findings)


def test_dangling_supersedes_back_reference_is_error(tmp_path):
    write_record(tmp_path, "old.md", make_old(superseded_by="[]", status="accepted"))
    write_record(tmp_path, "new.md", make_new(supersedes="[D-0001]"))
    findings = check_supersession(collect_records(tmp_path))
    assert any(
        f.severity is Severity.ERROR and f.record_id == "D-0002"
        for f in findings
    )


def test_supersedes_missing_target_is_error(tmp_path):
    write_record(tmp_path, "new.md", make_new(supersedes="[D-9999]"))
    findings = check_supersession(collect_records(tmp_path))
    assert any(
        f.severity is Severity.ERROR and f.record_id == "D-0002"
        for f in findings
    )
