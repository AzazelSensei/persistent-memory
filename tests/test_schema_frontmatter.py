import datetime

import pytest

from persistent_memory.schema import (
    Provenance,
    Record,
    RecordStatus,
    RecordType,
    parse_document,
    serialize_document,
)

SAMPLE = """---
id: D-0007
type: decision
status: proposed
date: 2026-06-02
project: example-app
provenance:
  session: S1254
  cwd: /Users/x/proj
  agent: claude-opus-4-8
tags:
  - veritabani
  - performans
supersedes: []
superseded-by: []
salience: 0.8
---
## Baglam / Problem
metin
"""


def test_parse_document():
    rec, body = parse_document(SAMPLE)
    assert rec.id == "D-0007"
    assert rec.type is RecordType.DECISION
    assert rec.provenance.session == "S1254"
    assert rec.tags == ["veritabani", "performans"]
    assert "## Baglam / Problem" in body


def test_parse_missing_frontmatter_raises():
    with pytest.raises(ValueError):
        parse_document("no frontmatter here")


def test_roundtrip_preserves_record_and_body():
    rec, body = parse_document(SAMPLE)
    text = serialize_document(rec, body)
    rec2, body2 = parse_document(text)
    assert rec2.model_dump() == rec.model_dump()
    assert body2.strip() == body.strip()


def test_serialize_uses_superseded_by_alias():
    rec = Record(
        id="L-0001",
        type=RecordType.LESSON,
        status=RecordStatus.PROPOSED,
        date=datetime.date(2026, 6, 2),
        project="p",
        provenance=Provenance(session="s", cwd="/c", agent="a"),
        salience=0.5,
    )
    text = serialize_document(rec, "## Ne oldu\nx")
    assert "superseded-by:" in text
    assert "superseded_by:" not in text
