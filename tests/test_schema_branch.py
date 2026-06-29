"""TDD: branch-aware provenance — failing tests written before implementation."""

import pytest
from pydantic import ValidationError

from persistent_memory.schema import Provenance, parse_document, serialize_document, Record, RecordType, RecordStatus
import datetime


SAMPLE_WITHOUT_BRANCH = """---
id: D-0007
type: decision
status: proposed
date: 2026-06-02
project: example-app
provenance:
  session: S1254
  cwd: /Users/x/proj
  agent: claude-opus-4-8
tags: []
supersedes: []
superseded-by: []
salience: 0.8
---
## Context

body
"""

SAMPLE_WITH_BRANCH = """---
id: D-0007
type: decision
status: proposed
date: 2026-06-02
project: example-app
provenance:
  session: S1254
  cwd: /Users/x/proj
  agent: claude-opus-4-8
  branch: faz1-backend
tags: []
supersedes: []
superseded-by: []
salience: 0.8
---
## Context

body
"""


# ---------------------------------------------------------------------------
# Schema: branch is optional — old records without it must still parse
# ---------------------------------------------------------------------------

def test_provenance_branch_defaults_to_none():
    p = Provenance(session="S1", cwd="/p", agent="a")
    assert p.branch is None


def test_provenance_branch_accepted():
    p = Provenance(session="S1", cwd="/p", agent="a", branch="feature-x")
    assert p.branch == "feature-x"


def test_provenance_branch_explicit_none():
    p = Provenance(session="S1", cwd="/p", agent="a", branch=None)
    assert p.branch is None


def test_old_frontmatter_without_branch_parses():
    rec, body = parse_document(SAMPLE_WITHOUT_BRANCH)
    assert rec.provenance.branch is None


def test_new_frontmatter_with_branch_parses():
    rec, body = parse_document(SAMPLE_WITH_BRANCH)
    assert rec.provenance.branch == "faz1-backend"


def test_serialize_round_trip_preserves_branch():
    rec, body = parse_document(SAMPLE_WITH_BRANCH)
    text = serialize_document(rec, body)
    rec2, body2 = parse_document(text)
    assert rec2.provenance.branch == "faz1-backend"


def test_serialize_round_trip_no_branch():
    rec, body = parse_document(SAMPLE_WITHOUT_BRANCH)
    text = serialize_document(rec, body)
    rec2, _ = parse_document(text)
    assert rec2.provenance.branch is None


def test_provenance_dump_includes_branch_when_set():
    p = Provenance(session="S1", cwd="/p", agent="a", branch="main")
    d = p.model_dump()
    assert "branch" in d
    assert d["branch"] == "main"
