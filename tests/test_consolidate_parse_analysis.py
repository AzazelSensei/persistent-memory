import shutil
from pathlib import Path

import pytest

from persistent_memory.consolidate import (
    GodNode,
    GraphAnalysis,
    SurpriseEdge,
    parse_analysis,
)

REAL_GRAPH = Path(__file__).parent / "fixtures" / "real_graph.json"
D0001 = "redis_yerine_inmemory_cache_d0001"
L0001 = "cache_invalidation_prod_cokmesi_l0001"


@pytest.fixture
def graph_path(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    target = out / "graph.json"
    shutil.copy(REAL_GRAPH, target)
    return target


def test_parse_returns_graph_analysis(graph_path):
    assert isinstance(parse_analysis(graph_path), GraphAnalysis)


def test_communities_computed_from_node_field(graph_path):
    a = parse_analysis(graph_path)
    assert set(a.communities) == {0, 1, 2}
    assert sorted(a.communities[1]) == sorted(
        ["redis_yerine_inmemory_cache_d0001", "redis_yerine_inmemory_cache_latency_problem"]
    )
    assert L0001 in a.communities[0]


def test_god_is_highest_degree_node(graph_path):
    a = parse_analysis(graph_path)
    top = a.gods[0]
    assert isinstance(top, GodNode)
    assert top.id == D0001
    assert top.degree == 4
    assert top.label == "In-Memory LRU Cache Kararı (D-0001)"


def test_cross_community_link_is_surprise(graph_path):
    a = parse_analysis(graph_path)
    assert a.surprises
    assert all(isinstance(s, SurpriseEdge) for s in a.surprises)
    labels = {frozenset((s.node_a, s.node_b)) for s in a.surprises}
    d_label = "In-Memory LRU Cache Kararı (D-0001)"
    l_label = "Cache Invalidation Prod Tutarsızlık Dersi (L-0001)"
    assert frozenset((d_label, l_label)) in labels


def test_surprise_carries_score_and_source_files(graph_path):
    a = parse_analysis(graph_path)
    d_label = "In-Memory LRU Cache Kararı (D-0001)"
    l_label = "Cache Invalidation Prod Tutarsızlık Dersi (L-0001)"
    edge = next(
        s
        for s in a.surprises
        if {s.node_a, s.node_b} == {d_label, l_label}
    )
    assert edge.relation == "references"
    assert edge.score == pytest.approx(1.0)
    assert edge.source_files == ["0001-cache-invalidation-prod-cokmesi.md"]


def test_knowledge_gaps_are_thin_nodes(graph_path):
    a = parse_analysis(graph_path)
    gap_ids = {g.id for g in a.knowledge_gaps}
    assert gap_ids == {
        "redis_yerine_inmemory_cache_redis",
        "redis_yerine_inmemory_cache_latency_problem",
    }
    for gap in a.knowledge_gaps:
        assert gap.degree < 2
        assert gap.label


def test_god_well_connected_node_not_a_gap(graph_path):
    a = parse_analysis(graph_path)
    gap_ids = {g.id for g in a.knowledge_gaps}
    assert D0001 not in gap_ids


def test_missing_graph_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="graph.json not found"):
        parse_analysis(tmp_path / "graphify-out" / "graph.json")
