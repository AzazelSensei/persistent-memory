import shutil
from pathlib import Path

import pytest

from persistent_memory.consolidate import (
    GraphSignal,
    boost_salience_from_gods,
    parse_analysis,
)

REAL_GRAPH = Path(__file__).parent / "fixtures" / "real_graph.json"
D0001_RECORD = "0001-redis-yerine-inmemory-cache"


@pytest.fixture
def graph_path(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    target = out / "graph.json"
    shutil.copy(REAL_GRAPH, target)
    return target


def test_god_node_record_gets_boost(graph_path):
    signal = GraphSignal.from_graph_json(graph_path)
    analysis = parse_analysis(graph_path)
    updated = boost_salience_from_gods(
        analysis=analysis,
        signal=signal,
        current_salience={D0001_RECORD: 0.5},
    )
    assert updated[D0001_RECORD] == pytest.approx(0.65)


def test_boost_clamped_at_max(graph_path):
    signal = GraphSignal.from_graph_json(graph_path)
    analysis = parse_analysis(graph_path)
    updated = boost_salience_from_gods(
        analysis=analysis,
        signal=signal,
        current_salience={D0001_RECORD: 0.95},
    )
    assert updated[D0001_RECORD] == 1.0


def test_record_not_in_salience_unchanged(graph_path):
    signal = GraphSignal.from_graph_json(graph_path)
    analysis = parse_analysis(graph_path)
    updated = boost_salience_from_gods(
        analysis=analysis,
        signal=signal,
        current_salience={"L-9999": 0.3},
    )
    assert "L-9999" not in updated
