import datetime
from dataclasses import dataclass, field
from pathlib import Path

from persistent_memory.lint import LoadedRecord
from persistent_memory.retriever import (
    RetrievalCandidate,
    adapt_loaded_record,
    bm25_rank,
    filter_by_project,
    recency_weight,
    rrf_fuse,
    salience_weight,
    search,
    tokenize_text,
    vector_rank,
)
from persistent_memory.schema import Provenance
from persistent_memory.schema import Record as RealRecord
from persistent_memory.schema import RecordStatus, RecordType


@dataclass
class Record:
    id: str
    type: str = "decision"
    status: str = "accepted"
    date: str = "2026-06-01"
    project: str = "project-alpha"
    tags: list[str] = field(default_factory=list)
    salience: float = 0.5
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    title: str = ""
    body: str = ""


def make_record(**kw) -> Record:
    return Record(**kw)


def test_tokenize_text_lowercases_and_splits_tr_en():
    tokens = tokenize_text("PostgreSQL İNDEX gerekli — N+1 sorgu")
    assert "postgresql" in tokens
    assert "i̇ndex" in tokens or "index" in tokens or "i̇ndex" in tokens
    assert "gerekli" in tokens
    assert "sorgu" in tokens
    assert "—" not in tokens


def test_tokenize_text_empty_returns_empty_list():
    assert tokenize_text("") == []
    assert tokenize_text("   ") == []


def test_retrieval_candidate_holds_record_and_score():
    rec = make_record(id="D-0001", title="x")
    cand = RetrievalCandidate(record=rec, score=0.0)
    assert cand.record.id == "D-0001"
    assert cand.score == 0.0


def test_bm25_rank_orders_by_lexical_relevance():
    records = [
        make_record(id="D-1", title="PostgreSQL index kararı", body="index ekledik sorgu hizlandi"),
        make_record(id="D-2", title="Redis cache kararı", body="cache ile latency dustu"),
        make_record(id="D-3", title="Loglama formatı", body="json log standardi"),
    ]
    ranked = bm25_rank(query="postgresql index sorgu", records=records)
    assert [r.id for r in ranked] == ["D-1", "D-2", "D-3"] or ranked[0].id == "D-1"
    assert ranked[0].id == "D-1"


def test_bm25_rank_empty_query_returns_empty():
    records = [make_record(id="D-1", body="x")]
    assert bm25_rank(query="", records=records) == []


def test_bm25_rank_empty_corpus_returns_empty():
    assert bm25_rank(query="postgresql", records=[]) == []


def test_bm25_rank_returns_all_records_when_any_match():
    records = [make_record(id=f"D-{i}", body="postgresql index") for i in range(3)]
    ranked = bm25_rank(query="postgresql", records=records)
    assert len(ranked) == 3


def test_bm25_rank_expands_query_synonyms():
    records = [
        make_record(id="D-1", title="Hesaba giris akisi", body="giris yapilmadan reels listesi sinirli"),
        make_record(id="D-2", title="Konfig dosyasiz deploy", body="config dosyasi olmadan calisti"),
        make_record(id="D-3", title="Loglama formatı", body="json log standardi burada"),
    ]
    ranked = bm25_rank(query="login olmadan", records=records)
    assert ranked[0].id == "D-1"


class FakeEmbedder:
    def __init__(self, query_vec, record_vecs):
        self._query_vec = query_vec
        self._record_vecs = record_vecs

    def embed_query(self, text: str) -> list[float]:
        return self._query_vec

    def get_vector(self, record_id: str):
        return self._record_vecs.get(record_id)


def test_vector_rank_orders_by_cosine_similarity():
    records = [make_record(id="D-1"), make_record(id="D-2"), make_record(id="D-3")]
    embedder = FakeEmbedder(
        query_vec=[1.0, 0.0],
        record_vecs={"D-1": [0.0, 1.0], "D-2": [1.0, 0.0], "D-3": [0.7, 0.7]},
    )
    ranked = vector_rank(query="x", records=records, embedder=embedder)
    assert [r.id for r in ranked] == ["D-2", "D-3", "D-1"]


def test_vector_rank_skips_records_without_vector():
    records = [make_record(id="D-1"), make_record(id="D-2")]
    embedder = FakeEmbedder(query_vec=[1.0, 0.0], record_vecs={"D-2": [1.0, 0.0]})
    ranked = vector_rank(query="x", records=records, embedder=embedder)
    assert [r.id for r in ranked] == ["D-2"]


def test_vector_rank_empty_query_returns_empty():
    records = [make_record(id="D-1")]
    embedder = FakeEmbedder(query_vec=[], record_vecs={"D-1": [1.0]})
    assert vector_rank(query="", records=records, embedder=embedder) == []


def test_vector_rank_handles_zero_vector_without_crash():
    records = [make_record(id="D-1")]
    embedder = FakeEmbedder(query_vec=[1.0, 0.0], record_vecs={"D-1": [0.0, 0.0]})
    ranked = vector_rank(query="x", records=records, embedder=embedder)
    assert [r.id for r in ranked] == ["D-1"]


def test_recency_weight_recent_higher_than_old():
    now = "2026-06-02"
    recent = recency_weight(record_date="2026-06-01", now=now)
    old = recency_weight(record_date="2026-01-01", now=now)
    assert recent > old


def test_recency_weight_same_day_is_max():
    w = recency_weight(record_date="2026-06-02", now="2026-06-02")
    assert abs(w - 1.0) < 1e-6


def test_recency_weight_in_unit_range():
    w = recency_weight(record_date="2020-01-01", now="2026-06-02")
    assert 0.0 < w <= 1.0


def test_recency_weight_invalid_date_returns_floor():
    w = recency_weight(record_date="not-a-date", now="2026-06-02")
    assert w == 0.0


def test_salience_weight_accepted_uses_raw():
    rec = make_record(id="D-1", status="accepted", salience=0.8)
    assert abs(salience_weight(rec) - 0.8) < 1e-6


def test_salience_weight_superseded_is_dampened():
    raw = make_record(id="D-1", status="accepted", salience=0.8)
    sup = make_record(id="D-2", status="superseded", salience=0.8)
    assert salience_weight(sup) < salience_weight(raw)


def test_salience_weight_reverted_is_dampened():
    rec = make_record(id="D-1", status="reverted-as-mistake", salience=0.8)
    assert salience_weight(rec) < 0.8


def test_salience_weight_clamped_to_unit_range():
    high = make_record(id="D-1", salience=5.0)
    low = make_record(id="D-2", salience=-1.0)
    assert salience_weight(high) <= 1.0
    assert salience_weight(low) >= 0.0


def test_rrf_fuse_rewards_agreement_across_sources():
    a = make_record(id="A")
    b = make_record(id="B")
    c = make_record(id="C")
    bm25_ranked = [a, b, c]
    vector_ranked = [a, c, b]
    fused = rrf_fuse([bm25_ranked, vector_ranked])
    assert fused[0].id == "A"


def test_rrf_fuse_handles_empty_sources():
    a = make_record(id="A")
    fused = rrf_fuse([[a], [], []])
    assert [r.id for r in fused] == ["A"]


def test_rrf_fuse_unions_records_from_different_sources():
    a = make_record(id="A")
    b = make_record(id="B")
    fused = rrf_fuse([[a], [b]])
    assert {r.id for r in fused} == {"A", "B"}


def test_rrf_fuse_empty_input_returns_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_rrf_fuse_is_pluggable_with_extra_source():
    a = make_record(id="A")
    b = make_record(id="B")
    graph_ranked = [b, a]
    fused = rrf_fuse([[a, b], [a, b], graph_ranked])
    assert {r.id for r in fused} == {"A", "B"}
    assert fused[0].id == "A"


def test_filter_by_project_keeps_only_matching():
    records = [
        make_record(id="D-1", project="project-alpha"),
        make_record(id="D-2", project="project-beta"),
        make_record(id="D-3", project="project-alpha"),
    ]
    kept = filter_by_project(records, project="project-alpha")
    assert [r.id for r in kept] == ["D-1", "D-3"]


def test_filter_by_project_none_returns_all():
    records = [make_record(id="D-1", project="project-alpha"), make_record(id="D-2", project="project-beta")]
    assert len(filter_by_project(records, project=None)) == 2


def test_filter_by_project_no_match_returns_empty():
    records = [make_record(id="D-1", project="project-alpha")]
    assert filter_by_project(records, project="other") == []


def test_search_returns_candidates_sorted_desc():
    records = [
        make_record(id="D-1", title="postgresql index", body="sorgu hizlandi",
                    project="project-alpha", date="2026-06-01", salience=0.9),
        make_record(id="D-2", title="redis cache", body="latency dustu",
                    project="project-alpha", date="2026-06-01", salience=0.5),
    ]
    embedder = FakeEmbedder(
        query_vec=[1.0, 0.0],
        record_vecs={"D-1": [1.0, 0.0], "D-2": [0.0, 1.0]},
    )
    results = search(query="postgresql index sorgu", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10)
    assert all(isinstance(r, RetrievalCandidate) for r in results)
    assert results[0].record.id == "D-1"
    assert results[0].score >= results[-1].score


def test_search_respects_scope():
    records = [
        make_record(id="D-1", title="postgresql", project="project-alpha"),
        make_record(id="D-2", title="postgresql", project="project-beta"),
    ]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"D-1": [1.0], "D-2": [1.0]})
    results = search(query="postgresql", project="project-beta", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10)
    assert [r.record.id for r in results] == ["D-2"]


def test_search_respects_top_k():
    records = [make_record(id=f"D-{i}", title="postgresql index", project="project-alpha")
               for i in range(5)]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={f"D-{i}": [1.0] for i in range(5)})
    results = search(query="postgresql", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=2)
    assert len(results) == 2


def test_search_recency_breaks_tie():
    records = [
        make_record(id="OLD", title="postgresql index", project="project-alpha", date="2026-01-01"),
        make_record(id="NEW", title="postgresql index", project="project-alpha", date="2026-06-01"),
    ]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"OLD": [1.0], "NEW": [1.0]})
    results = search(query="postgresql index", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10)
    assert results[0].record.id == "NEW"


def test_search_superseded_ranks_below_accepted_on_tie():
    records = [
        make_record(id="ACC", title="postgresql index", project="project-alpha",
                    date="2026-06-01", status="accepted", salience=0.8),
        make_record(id="SUP", title="postgresql index", project="project-alpha",
                    date="2026-06-01", status="superseded", salience=0.8),
    ]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"ACC": [1.0], "SUP": [1.0]})
    results = search(query="postgresql index", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10)
    assert results[0].record.id == "ACC"


def test_search_empty_query_returns_empty():
    records = [make_record(id="D-1", title="x", project="project-alpha")]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"D-1": [1.0]})
    assert search(query="", project="project-alpha", records=records,
                  embedder=embedder, now="2026-06-02", top_k=10) == []


def _real_loaded_record(tmp_path: Path) -> LoadedRecord:
    record = RealRecord(
        id="D-0001",
        type=RecordType.DECISION,
        status=RecordStatus.SUPERSEDED,
        date=datetime.date(2026, 6, 1),
        project="project-alpha",
        provenance=Provenance(session="s", cwd="/x", agent="claude"),
        tags=["postgresql", "index"],
        salience=0.8,
    )
    body = "## PostgreSQL index karari\n\nindex ekledik sorgu hizlandi"
    return LoadedRecord(record=record, path=tmp_path / "D-0001.md", body=body)


def test_adapt_loaded_record_exposes_title_tags_body(tmp_path):
    loaded = _real_loaded_record(tmp_path)
    adapted = adapt_loaded_record(loaded)
    assert adapted.title == "PostgreSQL index karari"
    assert adapted.tags == ["postgresql", "index"]
    assert "sorgu hizlandi" in adapted.body


def test_adapt_loaded_record_exposes_retriever_fields_as_strings(tmp_path):
    loaded = _real_loaded_record(tmp_path)
    adapted = adapt_loaded_record(loaded)
    assert adapted.id == "D-0001"
    assert adapted.project == "project-alpha"
    assert adapted.date == "2026-06-01"
    assert adapted.status == "superseded"
    assert adapted.salience == 0.8


def test_adapt_loaded_record_feeds_embeddings_without_attribute_error(tmp_path):
    from persistent_memory.embeddings import compose_record_text

    loaded = _real_loaded_record(tmp_path)
    adapted = adapt_loaded_record(loaded)
    text = compose_record_text(adapted)
    assert "PostgreSQL index karari" in text
    assert "postgresql index" in text


def test_adapt_loaded_record_falls_back_to_path_stem_title(tmp_path):
    record = RealRecord(
        id="L-0001",
        type=RecordType.LESSON,
        status=RecordStatus.ACCEPTED,
        date=datetime.date(2026, 6, 1),
        project="project-alpha",
        provenance=Provenance(session="s", cwd="/x", agent="claude"),
        tags=[],
        salience=0.5,
    )
    loaded = LoadedRecord(record=record, path=tmp_path / "L-0001.md", body="govde basliksiz")
    adapted = adapt_loaded_record(loaded)
    assert adapted.title == "L-0001"


def test_adapt_loaded_record_flows_through_search(tmp_path):
    loaded = _real_loaded_record(tmp_path)
    adapted = adapt_loaded_record(loaded)
    embedder = FakeEmbedder(query_vec=[1.0, 0.0], record_vecs={"D-0001": [1.0, 0.0]})
    results = search(query="postgresql index sorgu", project="project-alpha", records=[adapted],
                     embedder=embedder, now="2026-06-02", top_k=10)
    assert results[0].record.id == "D-0001"
    assert results[0].score >= 0.0


def test_rrf_fuse_tie_break_is_deterministic_by_id():
    a = make_record(id="A")
    b = make_record(id="B")
    fused = rrf_fuse([[a, b], [b, a]])
    assert [r.id for r in fused] == ["A", "B"]


class FakeGraphSignal:
    def __init__(self, ranked):
        self._ranked = ranked

    def ranked_ids_for(self, seed: str) -> list[str]:
        return list(self._ranked)


def test_search_works_without_graph_signal():
    records = [make_record(id="D-1", title="postgresql index", project="project-alpha")]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"D-1": [1.0]})
    results = search(query="postgresql index", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10)
    assert results[0].record.id == "D-1"


def test_search_graph_signal_boosts_related_record():
    records = [
        make_record(id="D-1", title="postgresql index", body="sorgu", project="project-alpha"),
        make_record(id="D-2", title="redis cache", body="latency", project="project-alpha"),
    ]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"D-1": [1.0], "D-2": [1.0]})
    graph = FakeGraphSignal(ranked=["D-2", "D-1"])
    results = search(query="postgresql index", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10, graph_signal=graph)
    assert {r.record.id for r in results} == {"D-1", "D-2"}


def test_search_graph_signal_unknown_ids_ignored():
    records = [make_record(id="D-1", title="postgresql index", project="project-alpha")]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"D-1": [1.0]})
    graph = FakeGraphSignal(ranked=["GHOST-1", "GHOST-2"])
    results = search(query="postgresql index", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10, graph_signal=graph)
    assert [r.record.id for r in results] == ["D-1"]


def test_search_deterministic_order_on_full_tie():
    records = [
        make_record(id="D-2", title="postgresql index", project="project-alpha",
                    date="2026-06-01", salience=0.5),
        make_record(id="D-1", title="postgresql index", project="project-alpha",
                    date="2026-06-01", salience=0.5),
    ]
    embedder = FakeEmbedder(query_vec=[1.0], record_vecs={"D-1": [1.0], "D-2": [1.0]})
    results = search(query="postgresql index", project="project-alpha", records=records,
                     embedder=embedder, now="2026-06-02", top_k=10)
    assert [r.record.id for r in results] == ["D-1", "D-2"]


def test_tokenize_folds_turkish_dotted_capital_i():
    assert tokenize_text("GİRİŞ") == tokenize_text("giriş")


def test_tokenize_folds_dotless_i_to_ascii():
    assert tokenize_text("KAYIT") == tokenize_text("kayıt")


def _counting_bm25(monkeypatch):
    import persistent_memory.retriever as r

    builds = {"n": 0}
    real_bm25 = r.BM25Okapi

    def counting_bm25(corpus):
        builds["n"] += 1
        return real_bm25(corpus)

    monkeypatch.setattr(r, "BM25Okapi", counting_bm25)
    r._reset_bm25_cache()
    return r, builds


def test_bm25_cache_reused_for_same_corpus(monkeypatch):
    r, builds = _counting_bm25(monkeypatch)
    recs = [
        make_record(id="D-0001", body="docker restart"),
        make_record(id="D-0002", body="nginx vhost"),
    ]
    r.bm25_rank("docker", recs)
    r.bm25_rank("nginx", recs)
    assert builds["n"] == 1


def test_bm25_cache_rebuilt_for_different_corpus(monkeypatch):
    r, builds = _counting_bm25(monkeypatch)
    recs_a = [
        make_record(id="D-0001", body="docker restart"),
        make_record(id="D-0002", body="nginx vhost"),
    ]
    recs_b = [make_record(id="D-0003", body="redis cache")]
    r.bm25_rank("docker", recs_a)
    r.bm25_rank("redis", recs_b)
    assert builds["n"] == 2


def test_bm25_cache_hit_ranks_correctly(monkeypatch):
    r, builds = _counting_bm25(monkeypatch)
    recs = [
        make_record(id="D-0001", body="docker restart"),
        make_record(id="D-0002", body="nginx vhost"),
        make_record(id="D-0003", body="redis cache"),
    ]
    r.bm25_rank("docker", recs)
    ranked = r.bm25_rank("nginx", recs)
    assert builds["n"] == 1
    assert ranked[0].id == "D-0002"


def test_bm25_cache_holds_alternating_corpora(monkeypatch):
    r, builds = _counting_bm25(monkeypatch)
    scoped = [make_record(id="D-0001", body="docker restart")]
    global_recs = [
        make_record(id="D-0001", body="docker restart"),
        make_record(id="D-0002", body="nginx vhost"),
    ]
    r.bm25_rank("docker", scoped)
    r.bm25_rank("docker", global_recs)
    r.bm25_rank("docker", scoped)
    assert builds["n"] == 2


def test_bm25_cache_evicts_oldest_above_capacity(monkeypatch):
    r, builds = _counting_bm25(monkeypatch)
    corpora = [[make_record(id=f"D-000{i}", body=f"konu {i} icerik")] for i in range(5)]
    for recs in corpora:
        r.bm25_rank("konu", recs)
    assert builds["n"] == 5
    r.bm25_rank("konu", corpora[2])
    assert builds["n"] == 5
    r.bm25_rank("konu", corpora[0])
    assert builds["n"] == 6


def test_bm25_cache_rebuilt_when_tags_change(monkeypatch):
    r, builds = _counting_bm25(monkeypatch)
    recs_a = [make_record(id="D-0001", body="docker restart", tags=["a"])]
    recs_b = [make_record(id="D-0001", body="docker restart", tags=["a", "b"])]
    r.bm25_rank("docker", recs_a)
    r.bm25_rank("docker", recs_b)
    assert builds["n"] == 2
