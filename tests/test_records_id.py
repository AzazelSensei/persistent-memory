from pathlib import Path

from persistent_memory.records import ensure_dirs, next_record_id
from persistent_memory.schema import RecordType


def test_first_id_is_0001(tmp_path: Path):
    ensure_dirs(tmp_path)
    assert next_record_id(tmp_path, RecordType.DECISION) == "D-0001"


def test_id_increments_per_type(tmp_path: Path):
    ensure_dirs(tmp_path)
    (tmp_path / "decisions" / "D-0001.md").write_text("x")
    (tmp_path / "decisions" / "D-0003.md").write_text("x")
    assert next_record_id(tmp_path, RecordType.DECISION) == "D-0004"


def test_id_independent_across_types(tmp_path: Path):
    ensure_dirs(tmp_path)
    (tmp_path / "decisions" / "D-0009.md").write_text("x")
    assert next_record_id(tmp_path, RecordType.LESSON) == "L-0001"


def test_id_ignores_non_matching_files(tmp_path: Path):
    ensure_dirs(tmp_path)
    (tmp_path / "decisions" / "index.md").write_text("x")
    (tmp_path / "decisions" / "D-0002.md").write_text("x")
    assert next_record_id(tmp_path, RecordType.DECISION) == "D-0003"
