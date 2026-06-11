from pathlib import Path

import pytest

from persistent_memory.records import (
    NewRecordSpec,
    SupersedeSpec,
    create_decision,
    read_record_by_id,
    supersede,
    update_status,
)
from persistent_memory.schema import Provenance, RecordStatus

PROV = Provenance(session="S1", cwd="/p", agent="a")


def _accepted_decision(tmp_path: Path) -> None:
    create_decision(tmp_path, NewRecordSpec(project="p", provenance=PROV))
    update_status(tmp_path, "D-0001", RecordStatus.ACCEPTED)


def test_supersede_creates_new_record(tmp_path: Path):
    _accepted_decision(tmp_path)
    spec = SupersedeSpec(
        old_id="D-0001",
        new_spec=NewRecordSpec(project="p", provenance=PROV),
        rationale="eski karar performans sorunu cikardi",
    )
    new_path = supersede(tmp_path, spec)
    assert new_path.name == "D-0002.md"


def test_supersede_links_bidirectional(tmp_path: Path):
    _accepted_decision(tmp_path)
    spec = SupersedeSpec(
        old_id="D-0001",
        new_spec=NewRecordSpec(project="p", provenance=PROV),
        rationale="gerekce",
    )
    supersede(tmp_path, spec)
    old_rec, _ = read_record_by_id(tmp_path, "D-0001")
    new_rec, new_body = read_record_by_id(tmp_path, "D-0002")
    assert old_rec.status is RecordStatus.SUPERSEDED
    assert old_rec.superseded_by == ["D-0002"]
    assert new_rec.supersedes == ["D-0001"]
    assert "## Supersession rationale" in new_body
    assert "gerekce" in new_body


def test_supersede_requires_rationale(tmp_path: Path):
    _accepted_decision(tmp_path)
    spec = SupersedeSpec(
        old_id="D-0001",
        new_spec=NewRecordSpec(project="p", provenance=PROV),
        rationale="   ",
    )
    with pytest.raises(ValueError):
        supersede(tmp_path, spec)


def test_supersede_already_dead_raises(tmp_path: Path):
    _accepted_decision(tmp_path)
    supersede(
        tmp_path,
        SupersedeSpec(
            old_id="D-0001",
            new_spec=NewRecordSpec(project="p", provenance=PROV),
            rationale="ilk supersession",
        ),
    )
    with pytest.raises(ValueError):
        supersede(
            tmp_path,
            SupersedeSpec(
                old_id="D-0001",
                new_spec=NewRecordSpec(project="p", provenance=PROV),
                rationale="tekrar supersede denemesi",
            ),
        )


def test_supersede_missing_old_raises(tmp_path: Path):
    spec = SupersedeSpec(
        old_id="D-9999",
        new_spec=NewRecordSpec(project="p", provenance=PROV),
        rationale="g",
    )
    with pytest.raises(FileNotFoundError):
        supersede(tmp_path, spec)
