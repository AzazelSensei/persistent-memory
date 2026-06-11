import json
import math
from types import SimpleNamespace

import httpx
import pytest

from persistent_memory.embeddings import (
    EmbeddingError,
    OllamaEmbedder,
    compose_record_text,
    embed_record,
    l2_normalize,
)

EMBED_DIM = 1024


def _fake_embed_handler(request):
    payload = json.loads(request.content)
    inputs = payload["input"]
    embeddings = [[float(i)] * EMBED_DIM for i, _ in enumerate(inputs)]
    return httpx.Response(200, json={"embeddings": embeddings})


def _nonzero_embed_handler(request):
    payload = json.loads(request.content)
    inputs = payload["input"]
    embeddings = [[float(i + 1)] * EMBED_DIM for i, _ in enumerate(inputs)]
    return httpx.Response(200, json={"embeddings": embeddings})


def _embedder_with_fake():
    return OllamaEmbedder(transport=httpx.MockTransport(_fake_embed_handler))


def test_connection_error_raises_meaningful_exception():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    embedder = OllamaEmbedder(transport=transport)

    with pytest.raises(EmbeddingError) as exc:
        embedder.embed_one("merhaba")

    assert "Ollama" in str(exc.value)


def test_embed_one_returns_1024_dim_vector():
    vec = _embedder_with_fake().embed_one("karar metni")
    assert len(vec) == EMBED_DIM


def test_embed_batch_returns_vector_per_input():
    vecs = _embedder_with_fake().embed_batch(["a", "b", "c"])
    assert len(vecs) == 3
    assert all(len(v) == EMBED_DIM for v in vecs)


def test_embed_batch_empty_returns_empty():
    assert _embedder_with_fake().embed_batch([]) == []


def test_embed_retries_on_transient_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("persistent_memory.embeddings.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky_handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("transient")
        return httpx.Response(200, json={"embeddings": [[1.0] * EMBED_DIM]})

    embedder = OllamaEmbedder(transport=httpx.MockTransport(flaky_handler))
    vec = embedder.embed_one("x")
    assert len(vec) == EMBED_DIM
    assert calls["n"] == 3


def test_embed_raises_after_max_retries(monkeypatch):
    monkeypatch.setattr("persistent_memory.embeddings.time.sleep", lambda _: None)

    def always_fail(request):
        raise httpx.ConnectError("down")

    embedder = OllamaEmbedder(transport=httpx.MockTransport(always_fail))
    with pytest.raises(EmbeddingError):
        embedder.embed_one("x")


def test_l2_normalize_unit_length():
    out = l2_normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-6)


def test_l2_normalize_zero_vector_stays_zero():
    assert l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_compose_record_text_includes_title_tags_body():
    record = SimpleNamespace(
        title="bge-m3 secimi",
        tags=["embedding", "yerel"],
        body="## Karar\nYerel bge-m3 kullan.",
    )
    text = compose_record_text(record)
    assert "bge-m3 secimi" in text
    assert "embedding" in text
    assert "yerel" in text
    assert "Yerel bge-m3 kullan." in text


def test_embed_record_returns_normalized_1024_vector():
    record = SimpleNamespace(title="t", tags=["a"], body="govde metni")
    embedder = OllamaEmbedder(transport=httpx.MockTransport(_nonzero_embed_handler))
    vec = embed_record(record, embedder)
    assert len(vec) == EMBED_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-6)
