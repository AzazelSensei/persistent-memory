from pathlib import Path

import pytest

from persistent_memory.records import (
    NewRecordSpec,
    create_decision,
    find_record_path,
    read_record_by_id,
)
from persistent_memory.schema import Provenance

PROV = Provenance(session="S1", cwd="/p", agent="a")


def test_find_record_path(tmp_path: Path):
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    found = find_record_path(tmp_path, "D-0001")
    assert found == tmp_path / "decisions" / "D-0001.md"


def test_read_record_by_id(tmp_path: Path):
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    rec, _ = read_record_by_id(tmp_path, "D-0001")
    assert rec.id == "D-0001"


def test_find_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        find_record_path(tmp_path, "D-9999")


def test_find_invalid_id_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        find_record_path(tmp_path, "Z-1")
