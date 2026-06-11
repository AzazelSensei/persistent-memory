from pathlib import Path

import pytest

from persistent_memory.records import (
    ImmutableRecordError,
    NewRecordSpec,
    create_decision,
    read_record_by_id,
    update_status,
    write_body,
)
from persistent_memory.schema import Provenance, RecordStatus

PROV = Provenance(session="S1", cwd="/p", agent="a")


def test_write_body_allowed_when_proposed(tmp_path: Path):
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    write_body(tmp_path, "D-0001", "## Karar\nyeni metin")
    _, body = read_record_by_id(tmp_path, "D-0001")
    assert "yeni metin" in body


def test_write_body_blocked_when_accepted(tmp_path: Path):
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    update_status(tmp_path, "D-0001", RecordStatus.ACCEPTED)
    with pytest.raises(ImmutableRecordError):
        write_body(tmp_path, "D-0001", "## Karar\ndegistirme girisimi")


def test_write_body_blocked_when_superseded(tmp_path: Path):
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    update_status(tmp_path, "D-0001", RecordStatus.SUPERSEDED)
    with pytest.raises(ImmutableRecordError):
        write_body(tmp_path, "D-0001", "x")
