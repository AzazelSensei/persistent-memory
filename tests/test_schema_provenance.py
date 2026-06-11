import pytest
from pydantic import ValidationError

from persistent_memory.schema import Provenance


def test_provenance_valid():
    p = Provenance(session="S1254", cwd="/Users/x/proj", agent="claude-opus-4-8")
    assert p.session == "S1254"
    assert p.cwd == "/Users/x/proj"
    assert p.agent == "claude-opus-4-8"


def test_provenance_requires_fields():
    with pytest.raises(ValidationError):
        Provenance(session="S1")


def test_provenance_dump_keys():
    p = Provenance(session="S1", cwd="/p", agent="a")
    assert set(p.model_dump().keys()) == {"session", "cwd", "agent"}
