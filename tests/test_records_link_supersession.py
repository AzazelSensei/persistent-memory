from pathlib import Path

import pytest

from persistent_memory.records import (
    NewRecordSpec,
    SupersessionLinkError,
    create_decision,
    link_supersession,
    read_record_by_id,
    update_status,
)
from persistent_memory.schema import Provenance, RecordStatus

PROV = Provenance(session="S1", cwd="/p", agent="a")


def _two_decisions(tmp_path: Path) -> None:
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    update_status(tmp_path, "D-0001", RecordStatus.ACCEPTED)
    update_status(tmp_path, "D-0002", RecordStatus.ACCEPTED)


def test_link_sets_bidirectional_fields(tmp_path: Path):
    _two_decisions(tmp_path)
    result = link_supersession(tmp_path, "D-0001", "D-0002")
    old_rec, _ = read_record_by_id(tmp_path, "D-0001")
    new_rec, _ = read_record_by_id(tmp_path, "D-0002")
    assert old_rec.status is RecordStatus.SUPERSEDED
    assert old_rec.superseded_by == ["D-0002"]
    assert new_rec.supersedes == ["D-0001"]
    assert result.already_linked is False
    assert result.old_record.id == "D-0001"
    assert result.new_record.id == "D-0002"


def test_link_is_idempotent(tmp_path: Path):
    _two_decisions(tmp_path)
    link_supersession(tmp_path, "D-0001", "D-0002")
    result = link_supersession(tmp_path, "D-0001", "D-0002")
    assert result.already_linked is True
    old_rec, _ = read_record_by_id(tmp_path, "D-0001")
    new_rec, _ = read_record_by_id(tmp_path, "D-0002")
    assert old_rec.superseded_by == ["D-0002"]
    assert new_rec.supersedes == ["D-0001"]


def test_link_same_record_raises(tmp_path: Path):
    _two_decisions(tmp_path)
    with pytest.raises(SupersessionLinkError, match="cannot supersede itself"):
        link_supersession(tmp_path, "D-0001", "D-0001")


def test_link_missing_record_raises(tmp_path: Path):
    _two_decisions(tmp_path)
    with pytest.raises(FileNotFoundError):
        link_supersession(tmp_path, "D-0001", "D-9999")
    with pytest.raises(FileNotFoundError):
        link_supersession(tmp_path, "D-9999", "D-0002")


def test_link_reverse_direction_conflict_raises(tmp_path: Path):
    _two_decisions(tmp_path)
    link_supersession(tmp_path, "D-0001", "D-0002")
    with pytest.raises(SupersessionLinkError, match="reverse direction"):
        link_supersession(tmp_path, "D-0002", "D-0001")


def test_link_reverted_old_record_raises(tmp_path: Path):
    _two_decisions(tmp_path)
    update_status(tmp_path, "D-0001", RecordStatus.REVERTED_AS_MISTAKE)
    with pytest.raises(SupersessionLinkError, match="reverted"):
        link_supersession(tmp_path, "D-0001", "D-0002")


def test_link_heals_partial_one_sided_link(tmp_path: Path):
    _two_decisions(tmp_path)
    from persistent_memory.records import find_record_path, read_record, _write_text_atomic
    from persistent_memory.schema import serialize_document

    old_path = find_record_path(tmp_path, "D-0001")
    old_rec, old_body = read_record(old_path)
    old_rec.superseded_by = ["D-0002"]
    _write_text_atomic(old_path, serialize_document(old_rec, old_body))

    link_supersession(tmp_path, "D-0001", "D-0002")
    old_rec, _ = read_record_by_id(tmp_path, "D-0001")
    new_rec, _ = read_record_by_id(tmp_path, "D-0002")
    assert old_rec.status is RecordStatus.SUPERSEDED
    assert old_rec.superseded_by == ["D-0002"]
    assert new_rec.supersedes == ["D-0001"]
