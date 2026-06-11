from pathlib import Path

from persistent_memory.records import NewRecordSpec, create_lesson, read_record
from persistent_memory.schema import Provenance, RecordStatus, RecordType

PROV = Provenance(session="S1", cwd="/p", agent="claude-opus-4-8")


def test_create_lesson_writes_file(tmp_path: Path):
    path = create_lesson(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    assert path == tmp_path / "lessons" / "L-0001.md"
    rec, body = read_record(path)
    assert rec.type is RecordType.LESSON
    assert rec.status is RecordStatus.PROPOSED
    assert "## What happened" in body


def test_lesson_id_independent_from_decision(tmp_path: Path):
    from persistent_memory.records import create_decision

    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    path = create_lesson(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    assert path.name == "L-0001.md"
