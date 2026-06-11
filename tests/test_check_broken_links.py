from persistent_memory.lint import Severity, check_broken_links, collect_records
from tests.test_collect_records import VALID_DECISION, write_record

LESSON_WITH_LINK = """---
id: L-0001
type: lesson
status: accepted
date: 2026-01-12
project: example-app
provenance: {session: s1, cwd: /tmp, agent: claude-opus-4-8}
tags: []
supersedes: []
superseded-by: []
salience: 0.6
---
## Ne oldu
x
## İlgili kararlar
[[D-0001]] ile bağlı, ayrıca [[D-9999]].
"""


def test_link_to_existing_id_is_clean(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    write_record(tmp_path, "l.md", LESSON_WITH_LINK.replace("[[D-9999]]", "[[D-0001]]"))
    findings = check_broken_links(collect_records(tmp_path))
    assert findings == []


def test_link_to_missing_id_is_error(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    write_record(tmp_path, "l.md", LESSON_WITH_LINK)
    findings = check_broken_links(collect_records(tmp_path))
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].record_id == "L-0001"
    assert "D-9999" in findings[0].message
    assert findings[0].check == "broken-link"
