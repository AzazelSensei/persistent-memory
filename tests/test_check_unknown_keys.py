from pathlib import Path

from persistent_memory.lint import Severity, check_unknown_keys
from tests.test_collect_records import VALID_DECISION


def write(dir_path: Path, name: str, text: str) -> Path:
    p = dir_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_known_keys_produce_no_finding(tmp_path):
    write(tmp_path, "d.md", VALID_DECISION)
    assert check_unknown_keys(tmp_path) == []


def test_aliased_superseded_by_key_is_known(tmp_path):
    text = VALID_DECISION.replace("superseded-by: []", "superseded-by: [D-0002]")
    write(tmp_path, "d.md", text)
    assert check_unknown_keys(tmp_path) == []


def test_typo_key_is_warning(tmp_path):
    text = VALID_DECISION.replace("salience: 0.8", "salience: 0.8\nsalence: 0.9")
    write(tmp_path, "d.md", text)
    findings = check_unknown_keys(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].check == "unknown-key"
    assert findings[0].record_id == "D-0001"
    assert "salence" in findings[0].message


def test_unknown_key_does_not_crash_on_malformed_frontmatter(tmp_path):
    write(tmp_path, "bad.md", "no frontmatter here\n")
    assert check_unknown_keys(tmp_path) == []
