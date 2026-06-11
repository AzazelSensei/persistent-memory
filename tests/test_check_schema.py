from pathlib import Path

from persistent_memory.lint import Severity, check_schema


VALID = """---
id: D-0001
type: decision
status: accepted
date: 2026-01-10
project: example-app
provenance: {session: s1, cwd: /tmp, agent: claude-opus-4-8}
tags: []
supersedes: []
superseded-by: []
salience: 0.5
---
## Karar
x
"""

INVALID_STATUS = VALID.replace("status: accepted", "status: kabul-edildi")
MISSING_ID = VALID.replace("id: D-0001\n", "")


def write(dir_path: Path, name: str, text: str) -> Path:
    p = dir_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_record_produces_no_schema_finding(tmp_path):
    write(tmp_path, "D-0001.md", VALID)
    findings = check_schema(tmp_path)
    assert findings == []


def test_invalid_status_enum_is_error(tmp_path):
    write(tmp_path, "D-0001.md", INVALID_STATUS)
    findings = check_schema(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].check == "schema"


def test_missing_required_id_is_error(tmp_path):
    write(tmp_path, "broken.md", MISSING_ID)
    findings = check_schema(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
