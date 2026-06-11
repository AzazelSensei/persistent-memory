import inspect
import json
from datetime import date

import httpx

import persistent_memory.daemon.services as services
from persistent_memory.embeddings import OllamaEmbedder, RetrievalAdapter, VectorIndex
from persistent_memory.records import NewRecordSpec, create_decision, create_lesson
from persistent_memory.schema import Provenance

EMBED_DIM = 1024


def _decision_body() -> str:
    return (
        "## Baglam / Problem\nLatency yuksekti.\n\n"
        "## Karar\nIn-memory LRU onbellek kullanildi.\n\n"
        "## Gerekce — neden bu, digerleri NEDEN elendi\nRedis ek yuk getiriyordu.\n\n"
        "## Sonuc / Ogrenilen\nLatency dustu.\n"
    )


def _lesson_body() -> str:
    return (
        "## Ne oldu\nStale read yasandi.\n\n"
        "## Neden hata/ogrenme\nCache invalidation yoktu.\n\n"
        "## Ne zaman fark edildi\nKullanici raporlayinca.\n\n"
        "## Genel kural\nOnbellek gecersiz kilma explicit yapilmali.\n"
    )


def _seed_records(records_dir):
    provenance = Provenance(session="s", cwd=str(records_dir), agent="claude")
    create_decision(
        records_dir,
        NewRecordSpec(
            project="pm-test",
            provenance=provenance,
            tags=["cache", "onbellek"],
            salience=0.9,
            date=date.today(),
            body=_decision_body(),
        ),
    )
    create_lesson(
        records_dir,
        NewRecordSpec(
            project="pm-test",
            provenance=provenance,
            tags=["cache", "invalidation"],
            salience=0.8,
            date=date.today(),
            body=_lesson_body(),
        ),
    )


def _mock_embed_transport():
    def handler(request):
        payload = json.loads(request.content)
        inputs = payload["input"]
        embeddings = [[float(i + 1)] * EMBED_DIM for i, _ in enumerate(inputs)]
        return httpx.Response(200, json={"embeddings": embeddings})

    return httpx.MockTransport(handler)


def test_retrieval_adapter_exposes_search_interface(tmp_path):
    embedder = OllamaEmbedder(transport=_mock_embed_transport())
    index = VectorIndex(tmp_path / ".index")
    adapter = RetrievalAdapter(embedder, index)
    assert hasattr(adapter, "embed_query")
    assert hasattr(adapter, "get_vector")
    vec = adapter.embed_query("onbellek")
    assert len(vec) == EMBED_DIM


def test_retrieval_adapter_get_vector_reads_from_index(tmp_path):
    embedder = OllamaEmbedder(transport=_mock_embed_transport())
    index = VectorIndex(tmp_path / ".index")
    index.upsert("D-0001", [0.5] * EMBED_DIM, content_hash="h")
    adapter = RetrievalAdapter(embedder, index)
    assert adapter.get_vector("D-0001") is not None
    assert len(adapter.get_vector("D-0001")) == EMBED_DIM
    assert adapter.get_vector("MISSING") is None


def test_run_search_does_not_reference_missing_embedder_methods():
    source = inspect.getsource(services.run_search) + inspect.getsource(
        services._build_retrieval_adapter
    )
    assert "embed_query" not in source
    assert "get_vector" not in source
    assert "RetrievalAdapter" in source


def _patch_embedder(monkeypatch):
    def fake_init(self, **kwargs):
        self._url = "http://localhost:11434/api/embed"
        self._model = "bge-m3"
        self._max_retries = 1
        self._client = httpx.Client(transport=_mock_embed_transport())

    monkeypatch.setattr("persistent_memory.embeddings.OllamaEmbedder.__init__", fake_init)


def test_run_search_returns_ranked_records_via_real_adapter_shape(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    _patch_embedder(monkeypatch)

    results = services.run_search("onbellek gecersiz kilma", records_dir=records_dir, top_k=10)
    assert results
    ids = {r["id"] for r in results}
    assert any(rid.startswith("D-") for rid in ids)
    assert any(rid.startswith("L-") for rid in ids)


def test_run_search_embeds_missing_records_on_demand(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    _patch_embedder(monkeypatch)

    services.run_search("onbellek", records_dir=records_dir, top_k=10)
    index = VectorIndex(records_dir / services.INDEX_DIRNAME)
    index.load()
    assert len(index) == 2


def test_collect_embed_views_caches_until_records_change(tmp_path):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    first = services._collect_embed_views(records_dir)
    assert len(first) == 2
    second = services._collect_embed_views(records_dir)
    assert second is first
    provenance = Provenance(session="s", cwd=str(records_dir), agent="claude")
    create_decision(
        records_dir,
        NewRecordSpec(project="pm-test", provenance=provenance, body=_decision_body()),
    )
    third = services._collect_embed_views(records_dir)
    assert len(third) == 3


def test_build_demote_ids_follows_record_changes(tmp_path):
    import frontmatter

    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    assert services._build_demote_ids(records_dir) == set()
    path = records_dir / "decisions" / "D-0001.md"
    post = frontmatter.load(str(path))
    post.metadata["superseded-by"] = ["D-0099"]
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    assert services._build_demote_ids(records_dir) == {"D-0001"}


def test_run_search_reembeds_changed_record_only(tmp_path, monkeypatch):
    from persistent_memory.records import write_body

    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    calls = {"n": 0}

    def handler(request):
        payload = json.loads(request.content)
        calls["n"] += len(payload["input"])
        return httpx.Response(
            200, json={"embeddings": [[1.0] * EMBED_DIM for _ in payload["input"]]}
        )

    transport = httpx.MockTransport(handler)

    def fake_init(self, **kwargs):
        self._url = "http://localhost:11434/api/embed"
        self._model = "bge-m3"
        self._max_retries = 1
        self._client = httpx.Client(transport=transport)

    monkeypatch.setattr("persistent_memory.embeddings.OllamaEmbedder.__init__", fake_init)

    services.run_search("onbellek", records_dir=records_dir, top_k=10)
    base = calls["n"]
    write_body(records_dir, "D-0001", "## Karar\nTamamen yeni icerik, vektor tazelenmeli.\n")
    services.run_search("onbellek ikinci sorgu", records_dir=records_dir, top_k=10)
    assert calls["n"] == base + 2
