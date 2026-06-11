from persistent_memory.lint import Severity, check_orphans, collect_records
from tests.test_collect_records import VALID_DECISION, write_record
from tests.test_check_broken_links import LESSON_WITH_LINK


def test_record_referenced_by_wikilink_is_not_orphan(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    write_record(tmp_path, "l.md", LESSON_WITH_LINK.replace("[[D-9999]]", "[[D-0001]]"))
    findings = check_orphans(collect_records(tmp_path))
    orphan_ids = {f.record_id for f in findings}
    assert "D-0001" not in orphan_ids


def test_unreferenced_record_is_info_orphan(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    findings = check_orphans(collect_records(tmp_path))
    assert len(findings) == 1
    assert findings[0].record_id == "D-0001"
    assert findings[0].severity is Severity.INFO
    assert findings[0].check == "orphan"


def test_supersedes_target_is_not_orphan(tmp_path):
    superseded = VALID_DECISION.replace("D-0001", "D-0001").replace(
        "status: accepted", "status: superseded"
    ).replace("superseded-by: []", "superseded-by: [D-0002]")
    newer = VALID_DECISION.replace("id: D-0001", "id: D-0002").replace(
        "supersedes: []", "supersedes: [D-0001]"
    )
    write_record(tmp_path, "old.md", superseded)
    write_record(tmp_path, "new.md", newer)
    findings = check_orphans(collect_records(tmp_path))
    orphan_ids = {f.record_id for f in findings}
    assert "D-0001" not in orphan_ids
