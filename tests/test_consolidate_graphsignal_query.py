from pathlib import Path
from persistent_memory.consolidate import GraphSignal

FIXTURE = Path(__file__).parent / "fixtures" / "graph_min.json"


def _signal() -> GraphSignal:
    return GraphSignal.from_graph_json(FIXTURE)


def test_neighbors_returns_connected_nodes():
    assert set(_signal().neighbors("auth_service")) == {"token_store", "payment_flow"}


def test_neighbors_unknown_node_returns_empty():
    assert _signal().neighbors("ghost") == []


def test_community_of_node():
    assert _signal().community_of("payment_flow") == 1


def test_shortest_path_between_connected_nodes():
    assert _signal().shortest_path("token_store", "payment_flow") == [
        "token_store", "auth_service", "payment_flow",
    ]


def test_shortest_path_no_route_returns_empty():
    assert _signal().shortest_path("auth_service", "orphan_note") == []
