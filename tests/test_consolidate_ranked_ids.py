from pathlib import Path
from persistent_memory.consolidate import GraphSignal

FIXTURE = Path(__file__).parent / "fixtures" / "graph_min.json"


def _signal() -> GraphSignal:
    return GraphSignal.from_graph_json(FIXTURE)


def test_ranked_ids_returns_record_ids_by_proximity():
    ranked = _signal().ranked_ids_for("D-0001")
    assert ranked[0] == "D-0001"
    assert "D-0002" in ranked


def test_ranked_ids_unknown_seed_returns_empty():
    assert _signal().ranked_ids_for("Z-9999") == []


def test_ranked_ids_orders_closer_before_farther():
    ranked = _signal().ranked_ids_for("D-0001")
    assert ranked.index("D-0001") < ranked.index("D-0002")


def test_ranked_ids_excludes_unreachable_records():
    ranked = _signal().ranked_ids_for("D-0001")
    assert "o1" not in ranked
