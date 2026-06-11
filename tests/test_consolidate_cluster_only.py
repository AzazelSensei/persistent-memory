import shutil
import subprocess
from pathlib import Path

import pytest

import persistent_memory.consolidate as cz
from persistent_memory.consolidate import (
    ConsolidationResult,
    GraphNotBuiltError,
    run_consolidation,
)

REAL_GRAPH = Path(__file__).parent / "fixtures" / "real_graph.json"


@pytest.fixture
def corpus_with_graph(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    shutil.copy(REAL_GRAPH, out / "graph.json")
    return tmp_path


def test_cheap_path_reuses_existing_graph_no_subprocess(corpus_with_graph, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no subprocess should run on the cheap path")

    monkeypatch.setattr(subprocess, "run", boom)
    result = run_consolidation(
        corpus_root=corpus_with_graph,
        current_salience={},
        should_full_build=False,
    )
    assert isinstance(result, ConsolidationResult)


def test_cheap_path_does_not_call_full_build(corpus_with_graph, monkeypatch):
    called = {"full": 0}
    monkeypatch.setattr(cz, "run_full_build", lambda root: called.__setitem__("full", called["full"] + 1))
    run_consolidation(
        corpus_root=corpus_with_graph,
        current_salience={},
        should_full_build=False,
    )
    assert called["full"] == 0


def test_cheap_path_missing_graph_raises(tmp_path):
    with pytest.raises(GraphNotBuiltError, match="full build required"):
        run_consolidation(
            corpus_root=tmp_path,
            current_salience={},
            should_full_build=False,
        )
