import json

import httpx
import pytest

from persistent_memory import transcript_rag
from persistent_memory.embeddings import OllamaEmbedder
from persistent_memory.transcript_rag import Chunk, TranscriptRagIndex

EMBED_DIM = 8


def _axis(token_to_axis, text):
    axis = token_to_axis.get(text.strip().split("\n")[0], 0) % EMBED_DIM
    vec = [0.0] * EMBED_DIM
    vec[axis] = 1.0
    return vec


def _make_embedder(token_to_axis):
    def handler(request):
        payload = json.loads(request.content)
        embeddings = [_axis(token_to_axis, t) for t in payload["input"]]
        return httpx.Response(200, json={"embeddings": embeddings})

    return OllamaEmbedder(transport=httpx.MockTransport(handler))


def _chunk(text, *, project="proj", session="sess-a", ordinal=0):
    return Chunk(project=project, session_id=session, text=text, timestamp="2026-06-01T00:00:00Z", ordinal=ordinal)


def test_add_chunks_returns_added_count():
    mapping = {"redis": 1, "graph": 2, "test": 3}
    embedder = _make_embedder(mapping)
    index = TranscriptRagIndex()
    added = index.add_chunks(
        [_chunk("redis"), _chunk("graph", ordinal=1), _chunk("test", ordinal=2)], embedder
    )
    assert added == 3
    assert len(index) == 3


def test_add_chunks_dedups_by_content_hash():
    embedder = _make_embedder({"redis": 1})
    index = TranscriptRagIndex()
    index.add_chunks([_chunk("redis")], embedder)
    added = index.add_chunks([_chunk("redis")], embedder)
    assert added == 0
    assert len(index) == 1


def test_save_load_roundtrip(tmp_path):
    embedder = _make_embedder({"redis": 1, "graph": 2})
    index = TranscriptRagIndex()
    index.add_chunks([_chunk("redis"), _chunk("graph", ordinal=1)], embedder)
    index.save(tmp_path / "idx")

    assert (tmp_path / "idx" / "vectors.npy").exists()
    assert (tmp_path / "idx" / "meta.json").exists()

    reloaded = TranscriptRagIndex()
    reloaded.load(tmp_path / "idx")
    assert len(reloaded) == 2


def test_load_dedup_persists_across_reload(tmp_path):
    embedder = _make_embedder({"redis": 1})
    index = TranscriptRagIndex()
    index.add_chunks([_chunk("redis")], embedder)
    index.save(tmp_path / "idx")

    reloaded = TranscriptRagIndex()
    reloaded.load(tmp_path / "idx")
    added = reloaded.add_chunks([_chunk("redis")], embedder)
    assert added == 0
    assert len(reloaded) == 1


def test_query_returns_nearest_chunk():
    mapping = {"redis": 1, "graph": 2, "deploy": 3}
    embedder = _make_embedder(mapping)
    index = TranscriptRagIndex()
    index.add_chunks(
        [_chunk("redis"), _chunk("graph", ordinal=1), _chunk("deploy", ordinal=2)], embedder
    )
    query_vec = embedder.embed_one("graph")
    results = index.query(query_vec, top_k=1)
    assert len(results) == 1
    assert results[0]["text"] == "graph"
    assert results[0]["score"] == pytest.approx(1.0, abs=1e-5)
    assert results[0]["session_id"] == "sess-a"
    assert results[0]["project"] == "proj"


def test_query_project_filter():
    mapping = {"redis": 1, "graph": 2}
    embedder = _make_embedder(mapping)
    index = TranscriptRagIndex()
    index.add_chunks(
        [
            Chunk(project="alpha", session_id="s1", text="redis", timestamp=None, ordinal=0),
            Chunk(project="beta", session_id="s2", text="graph", timestamp=None, ordinal=0),
        ],
        embedder,
    )
    query_vec = embedder.embed_one("redis")
    filtered = index.query(query_vec, top_k=5, project="beta")
    assert all(r["project"] == "beta" for r in filtered)
    assert all(r["text"] != "redis" for r in filtered)


def test_query_empty_index_returns_empty():
    assert TranscriptRagIndex().query([1.0] + [0.0] * (EMBED_DIM - 1), top_k=5) == []
