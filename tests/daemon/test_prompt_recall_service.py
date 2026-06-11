import json
from datetime import date

import httpx

import persistent_memory.daemon.services as services
from persistent_memory.records import NewRecordSpec, create_decision, create_lesson
from persistent_memory.schema import Provenance

EMBED_DIM = 1024


def _decision_body() -> str:
    return (
        "# N+1 sorgu batch fetch ile cozuldu\n\n"
        "## Bağlam / Problem\nDongu icinde DB sorgusu vardi.\n\n"
        "## Karar\nDongu disinda tek JOIN ile batch fetch yapildi.\n\n"
        "## Gerekçe — neden bu, digerleri NEDEN elendi\nN+1 latency yuksekti.\n\n"
        "## Sonuç / Öğrenilen\nLatency dustu.\n"
    )


def _lesson_body() -> str:
    return (
        "# Silmeden once butunlugu dogrula\n\n"
        "## Ne oldu\nUpload yarim kalmisken silme istendi.\n\n"
        "## Neden hata/öğrenme\nArka plan task killed olmustu.\n\n"
        "## Ne zaman fark edildi\nGercek durum kontrol edilince.\n\n"
        "## Genel kural\nYukleme sonrasi silmeden once bagimsizca dogrula.\n"
    )


def _seed_records(records_dir, *, project="pm-test"):
    provenance = Provenance(session="s", cwd=str(records_dir), agent="claude")
    create_decision(
        records_dir,
        NewRecordSpec(
            project=project,
            provenance=provenance,
            tags=["n+1", "batch"],
            salience=0.9,
            date=date.today(),
            body=_decision_body(),
        ),
    )
    create_lesson(
        records_dir,
        NewRecordSpec(
            project=project,
            provenance=provenance,
            tags=["silme", "dogrula"],
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


def _patch_embedder(monkeypatch):
    def fake_init(self, **kwargs):
        self._url = "http://localhost:11434/api/embed"
        self._model = "bge-m3"
        self._max_retries = 1
        self._client = httpx.Client(transport=_mock_embed_transport())

    monkeypatch.setattr("persistent_memory.embeddings.OllamaEmbedder.__init__", fake_init)


def test_prompt_recall_returns_formatted_block(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    _patch_embedder(monkeypatch)

    block = services.run_prompt_recall(
        "N+1 sorgu batch fetch", records_dir=records_dir, project="pm-test"
    )
    assert block
    assert "[D-0001]" in block
    assert "N+1 sorgu batch fetch ile cozuldu" in block
    assert "(pm-test)" in block
    assert "batch fetch" in block


def test_prompt_recall_pulls_genel_kural_gist_for_lesson(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    _patch_embedder(monkeypatch)

    block = services.run_prompt_recall(
        "silmeden once dogrula", records_dir=records_dir, project="pm-test"
    )
    assert "[L-0001]" in block
    assert "silmeden once bagimsizca dogrula" in block


def test_prompt_recall_is_budget_bounded(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    _patch_embedder(monkeypatch)

    block = services.run_prompt_recall(
        "N+1 batch silme", records_dir=records_dir, project="pm-test", budget=40
    )
    assert len(block) // 4 <= 40 + 20


def test_prompt_recall_empty_when_no_records(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    _patch_embedder(monkeypatch)

    block = services.run_prompt_recall("herhangi", records_dir=records_dir, project="pm-test")
    assert block == ""


def test_prompt_recall_surfaces_relevant_cross_project(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir, project="pm-test")
    _patch_embedder(monkeypatch)

    block = services.run_prompt_recall(
        "N+1 sorgu", records_dir=records_dir, project="baska-proje"
    )
    assert "pm-test" in block


def test_prompt_recall_empty_when_embedder_down(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)

    def boom_init(self, **kwargs):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("persistent_memory.embeddings.OllamaEmbedder.__init__", boom_init)

    block = services.run_prompt_recall(
        "N+1 sorgu", records_dir=records_dir, project="pm-test"
    )
    assert block == ""


def test_prompt_recall_empty_query_returns_empty(tmp_path, monkeypatch):
    records_dir = tmp_path / "records"
    _seed_records(records_dir)
    _patch_embedder(monkeypatch)

    assert services.run_prompt_recall("   ", records_dir=records_dir, project="pm-test") == ""


def test_gist_supports_english_canonical_headings():
    decision_body = (
        "# Cache layer chosen\n\n"
        "## Context\nLatency was high.\n\n"
        "## Decision\nUse an in-memory LRU cache.\n\n"
        "## Rationale\nRedis added operational overhead.\n"
    )
    lesson_body = (
        "# Verify before deleting\n\n"
        "## What happened\nDeletion was requested mid-upload.\n\n"
        "## General rule\nIndependently verify integrity before deleting.\n"
    )
    decision_gist = services._gist_from_body(
        decision_body, preferred_headings=services.DECISION_GIST_HEADINGS
    )
    lesson_gist = services._gist_from_body(
        lesson_body, preferred_headings=services.LESSON_GIST_HEADINGS
    )
    assert decision_gist == "Use an in-memory LRU cache."
    assert lesson_gist == "Independently verify integrity before deleting."
