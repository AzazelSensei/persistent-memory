import datetime

import pytest
from pydantic import ValidationError

from persistent_memory.schema import Provenance, Record, RecordStatus, RecordType

PROV = Provenance(session="S1", cwd="/p", agent="a")


def _base(**over):
    data = dict(
        id="D-0007",
        type=RecordType.DECISION,
        status=RecordStatus.PROPOSED,
        date=datetime.date(2026, 6, 2),
        project="example-app",
        provenance=PROV,
        tags=["db"],
        supersedes=[],
        superseded_by=[],
        salience=0.8,
    )
    data.update(over)
    return data


def test_record_valid():
    r = Record(**_base())
    assert r.id == "D-0007"
    assert r.type is RecordType.DECISION
    assert r.salience == 0.8


def test_record_defaults_empty_lists():
    data = _base()
    del data["tags"]
    del data["supersedes"]
    del data["superseded_by"]
    r = Record(**data)
    assert r.tags == []
    assert r.supersedes == []
    assert r.superseded_by == []


def test_id_must_match_type_prefix():
    with pytest.raises(ValidationError):
        Record(**_base(id="X-0007"))
    with pytest.raises(ValidationError):
        Record(**_base(id="D-7"))


def test_decision_id_prefix_mismatch_rejected():
    with pytest.raises(ValidationError):
        Record(**_base(id="L-0007", type=RecordType.DECISION))


def test_salience_bounds():
    with pytest.raises(ValidationError):
        Record(**_base(salience=1.5))
    with pytest.raises(ValidationError):
        Record(**_base(salience=-0.1))


def test_alias_superseded_by():
    r = Record(**_base())
    dumped = r.model_dump(by_alias=True)
    assert "superseded-by" in dumped
