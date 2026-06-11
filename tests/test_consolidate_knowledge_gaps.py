from pathlib import Path
from persistent_memory.consolidate import GraphSignal, flag_knowledge_gaps, KnowledgeGap

GRAPH = Path(__file__).parent / "fixtures" / "graph_min.json"


def test_orphan_node_flagged():
    signal = GraphSignal.from_graph_json(GRAPH)
    gaps = flag_knowledge_gaps(signal)
    labels = {g.label for g in gaps}
    assert "OrphanNote" in labels


def test_well_connected_node_not_flagged():
    signal = GraphSignal.from_graph_json(GRAPH)
    gaps = flag_knowledge_gaps(signal)
    labels = {g.label for g in gaps}
    assert "AuthService" not in labels


def test_gap_is_typed_with_degree():
    signal = GraphSignal.from_graph_json(GRAPH)
    gap = next(g for g in flag_knowledge_gaps(signal) if g.label == "OrphanNote")
    assert isinstance(gap, KnowledgeGap)
    assert gap.degree == 0
    assert gap.node_id == "orphan_note"
