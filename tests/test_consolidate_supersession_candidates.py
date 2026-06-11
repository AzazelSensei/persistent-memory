import shutil
from pathlib import Path

import pytest

from persistent_memory.consolidate import (
    SupersessionCandidate,
    map_surprises_to_supersession_candidates,
    parse_analysis,
)

REAL_GRAPH = Path(__file__).parent / "fixtures" / "real_graph.json"
D_LABEL = "In-Memory LRU Cache Kararı (D-0001)"
L_LABEL = "Cache Invalidation Prod Tutarsızlık Dersi (L-0001)"


@pytest.fixture
def analysis(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    target = out / "graph.json"
    shutil.copy(REAL_GRAPH, target)
    return parse_analysis(target)


def test_cross_community_reference_becomes_candidate(analysis):
    candidates = map_surprises_to_supersession_candidates(analysis)
    assert candidates
    assert all(isinstance(c, SupersessionCandidate) for c in candidates)
    pairs = {frozenset((c.source_label, c.target_label)) for c in candidates}
    assert frozenset((D_LABEL, L_LABEL)) in pairs


def test_candidate_carries_source_files_and_score(analysis):
    candidates = map_surprises_to_supersession_candidates(analysis)
    candidate = next(
        c for c in candidates if {c.source_label, c.target_label} == {D_LABEL, L_LABEL}
    )
    assert candidate.relation == "references"
    assert candidate.score == pytest.approx(1.0)
    assert candidate.source_files == ["0001-cache-invalidation-prod-cokmesi.md"]


def test_low_score_surprise_excluded(analysis):
    candidates = map_surprises_to_supersession_candidates(analysis)
    assert all(c.score >= 0.66 for c in candidates)
