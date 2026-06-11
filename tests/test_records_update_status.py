from pathlib import Path

from persistent_memory.records import (
    NewRecordSpec,
    create_decision,
    read_record_by_id,
    update_status,
)
from persistent_memory.schema import Provenance, RecordStatus

PROV = Provenance(session="S1", cwd="/p", agent="a")


def test_update_status_changes_status(tmp_path: Path):
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    update_status(tmp_path, "D-0001", RecordStatus.ACCEPTED)
    rec, _ = read_record_by_id(tmp_path, "D-0001")
    assert rec.status is RecordStatus.ACCEPTED


def test_update_status_preserves_body(tmp_path: Path):
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    _, body_before = read_record_by_id(tmp_path, "D-0001")
    update_status(tmp_path, "D-0001", RecordStatus.ACCEPTED)
    _, body_after = read_record_by_id(tmp_path, "D-0001")
    assert body_after.strip() == body_before.strip()
