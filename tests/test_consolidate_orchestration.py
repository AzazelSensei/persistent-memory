import shutil
from pathlib import Path

import pytest

import persistent_memory.consolidate as cz
from persistent_memory.consolidate import ConsolidationResult, run_consolidation

REAL_GRAPH = Path(__file__).parent / "fixtures" / "real_graph.json"
D0001_RECORD = "0001-redis-yerine-inmemory-cache"


@pytest.fixture
def corpus(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    shutil.copy(REAL_GRAPH, out / "graph.json")
    return tmp_path


def test_cheap_path_skips_build(corpus, monkeypatch):
    calls = {"full": 0}
    monkeypatch.setattr(cz, "run_full_build", lambda root: calls.__setitem__("full", calls["full"] + 1))
    result = run_consolidation(
        corpus_root=corpus, current_salience={}, should_full_build=False,
    )
    assert calls["full"] == 0
    assert isinstance(result, ConsolidationResult)


def test_full_build_path_invoked(corpus, monkeypatch):
    calls = {"full": 0}
    monkeypatch.setattr(cz, "run_full_build", lambda root: calls.__setitem__("full", calls["full"] + 1))
    run_consolidation(corpus_root=corpus, current_salience={}, should_full_build=True)
    assert calls["full"] == 1


def test_result_aggregates_all_signals(corpus, monkeypatch):
    monkeypatch.setattr(cz, "run_full_build", lambda root: None)
    result = run_consolidation(
        corpus_root=corpus,
        current_salience={D0001_RECORD: 0.5},
        should_full_build=False,
    )
    assert len(result.supersession_candidates) >= 1
    gap_ids = {g.node_id for g in result.knowledge_gaps}
    assert "redis_yerine_inmemory_cache_redis" in gap_ids
    assert result.salience_updates[D0001_RECORD] == pytest.approx(0.65)
