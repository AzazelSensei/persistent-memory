import datetime
from pathlib import Path

from persistent_memory.records import NewRecordSpec, create_decision, read_record
from persistent_memory.schema import Provenance, RecordStatus, RecordType

PROV = Provenance(session="S1", cwd="/p", agent="claude-opus-4-8")


def test_create_decision_writes_file(tmp_path: Path):
    spec = NewRecordSpec(project="example-app", provenance=PROV, tags=["db"], salience=0.8, date=datetime.date(2026, 6, 2))
    path = create_decision(tmp_path, spec)
    assert path == tmp_path / "decisions" / "D-0001.md"
    assert path.exists()


def test_created_decision_is_proposed(tmp_path: Path):
    spec = NewRecordSpec(project="example-app", provenance=PROV)
    path = create_decision(tmp_path, spec)
    rec, body = read_record(path)
    assert rec.type is RecordType.DECISION
    assert rec.status is RecordStatus.PROPOSED
    assert rec.id == "D-0001"
    assert "## Decision" in body


def test_create_decision_defaults_date_today(tmp_path: Path):
    spec = NewRecordSpec(project="p", provenance=PROV)
    path = create_decision(tmp_path, spec)
    rec, _ = read_record(path)
    assert rec.date == datetime.date.today()


def test_create_decision_increments(tmp_path: Path):
    spec = NewRecordSpec(project="p", provenance=PROV)
    create_decision(tmp_path, spec)
    second = create_decision(tmp_path, spec)
    assert second.name == "D-0002.md"
