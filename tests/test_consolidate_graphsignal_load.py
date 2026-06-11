from pathlib import Path
from persistent_memory.consolidate import GraphSignal

FIXTURE = Path(__file__).parent / "fixtures" / "graph_min.json"


def test_loads_graph_with_expected_node_count():
    signal = GraphSignal.from_graph_json(FIXTURE)
    assert signal.node_count == 4


def test_loads_edges_via_links_key():
    signal = GraphSignal.from_graph_json(FIXTURE)
    assert signal.edge_count == 2


def test_node_label_lookup():
    signal = GraphSignal.from_graph_json(FIXTURE)
    assert signal.label_of("auth_service") == "AuthService"


def test_missing_graph_file_raises():
    import pytest
    with pytest.raises(FileNotFoundError, match="graph.json not found"):
        GraphSignal.from_graph_json(Path("/nope/graph.json"))
