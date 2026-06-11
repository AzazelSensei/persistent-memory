from dataclasses import dataclass, field

from persistent_memory.recall import build_recall_block, estimate_tokens
from persistent_memory.retriever import RetrievalCandidate


@dataclass
class Record:
    id: str
    type: str = "decision"
    status: str = "accepted"
    date: str = "2026-06-01"
    project: str = "project-alpha"
    tags: list[str] = field(default_factory=list)
    salience: float = 0.8
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    title: str = ""
    body: str = ""


def make_candidate(rid: str, title: str, body: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(record=Record(id=rid, title=title, body=body), score=score)


def fake_searcher(candidates):
    def _search(**kwargs):
        return candidates
    return _search


def test_estimate_tokens_grows_with_length():
    assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)


def test_build_recall_block_includes_top_record_id():
    cands = [make_candidate("D-1", "postgresql index", "sorgu hizlandi", 0.9)]
    block = build_recall_block(project="project-alpha", searcher=fake_searcher(cands))
    assert "D-1" in block
    assert "postgresql index" in block


def test_build_recall_block_respects_token_budget():
    cands = [make_candidate(f"D-{i}", f"title {i}", "x" * 4000, 0.9 - i * 0.01)
             for i in range(20)]
    block = build_recall_block(project="project-alpha", searcher=fake_searcher(cands),
                               token_budget=1200)
    assert estimate_tokens(block) <= 1200
    assert "D-0" in block
    assert "D-19" not in block


def test_build_recall_block_drops_low_visibility_candidates():
    cands = [
        make_candidate("HIGH", "alpha", "body", 0.9),
        make_candidate("LOW", "beta", "body", 0.0001),
    ]
    block = build_recall_block(project="project-alpha", searcher=fake_searcher(cands))
    assert "HIGH" in block
    assert "LOW" not in block


def test_build_recall_block_empty_results_returns_empty_string():
    block = build_recall_block(project="project-alpha", searcher=fake_searcher([]))
    assert block == ""


def test_build_recall_block_passes_project_to_searcher():
    captured = {}

    def _search(**kwargs):
        captured.update(kwargs)
        return []

    build_recall_block(project="project-beta", searcher=_search)
    assert captured["project"] == "project-beta"
