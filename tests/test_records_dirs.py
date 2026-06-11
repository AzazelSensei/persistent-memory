from pathlib import Path

from persistent_memory.records import dir_for_type, ensure_dirs
from persistent_memory.schema import RecordType


def test_ensure_dirs_creates(tmp_path: Path):
    ensure_dirs(tmp_path)
    assert (tmp_path / "decisions").is_dir()
    assert (tmp_path / "lessons").is_dir()


def test_dir_for_type(tmp_path: Path):
    assert dir_for_type(tmp_path, RecordType.DECISION) == tmp_path / "decisions"
    assert dir_for_type(tmp_path, RecordType.LESSON) == tmp_path / "lessons"
    assert dir_for_type(tmp_path, RecordType.PRINCIPLE) == tmp_path / "principles"
