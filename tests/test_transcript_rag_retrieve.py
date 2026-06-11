import json

import httpx

from persistent_memory import transcript_rag
from persistent_memory.embeddings import OllamaEmbedder

EMBED_DIM = 8


def _line(**kw):
    return json.dumps(kw)


def _user(cwd, text, ts):
    return _line(type="user", cwd=cwd, timestamp=ts, message={"role": "user", "content": text})


def _assistant(cwd, text, ts):
    return _line(
        type="assistant",
        cwd=cwd,
        timestamp=ts,
        message={"role": "assistant", "content": [{"type": "text", "text": text}]},
    )


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _keyword_axis(text):
    lowered = text.lower()
    if "redis" in lowered:
        return 1
    if "deploy" in lowered:
        return 2
    return 0


def _make_embedder():
    def handler(request):
        payload = json.loads(request.content)
        out = []
        for t in payload["input"]:
            vec = [0.0] * EMBED_DIM
            vec[_keyword_axis(t)] = 1.0
            out.append(vec)
        return httpx.Response(200, json={"embeddings": out})

    return OllamaEmbedder(transport=httpx.MockTransport(handler))


CWD_A = "/Users/dev/Desktop/alpha"
CWD_B = "/Users/dev/Desktop/beta"


def _projects_root(tmp_path):
    root = tmp_path / "projects"
    _write(
        root / "-Users-dev-Desktop-alpha" / "s1.jsonl",
        [
            _user(CWD_A, "redis cache ekleyelim", "2026-06-01T12:00:00.000Z"),
            _assistant(CWD_A, "redis ile N+1 cozulur", "2026-06-01T12:00:01.000Z"),
        ],
    )
    _write(
        root / "-Users-dev-Desktop-beta" / "s2.jsonl",
        [
            _user(CWD_B, "deploy pipeline kuralim", "2026-06-02T12:00:00.000Z"),
            _assistant(CWD_B, "deploy icin github actions", "2026-06-02T12:00:01.000Z"),
        ],
    )
    return root


def test_build_transcript_index_returns_count(tmp_path):
    root = _projects_root(tmp_path)
    index_dir = tmp_path / "idx"
    count = transcript_rag.build_transcript_index(
        index_dir, projects_root=root, embedder=_make_embedder()
    )
    assert count >= 2
    assert (index_dir / "vectors.npy").exists()


def test_build_transcript_index_is_idempotent(tmp_path):
    root = _projects_root(tmp_path)
    index_dir = tmp_path / "idx"
    embedder = _make_embedder()
    first = transcript_rag.build_transcript_index(index_dir, projects_root=root, embedder=embedder)
    second = transcript_rag.build_transcript_index(index_dir, projects_root=root, embedder=embedder)
    assert first == second
    loaded = transcript_rag.TranscriptRagIndex()
    loaded.load(index_dir)
    assert len(loaded) == first


def test_retrieve_for_text_returns_ranked_passages(tmp_path):
    root = _projects_root(tmp_path)
    index_dir = tmp_path / "idx"
    embedder = _make_embedder()
    transcript_rag.build_transcript_index(index_dir, projects_root=root, embedder=embedder)
    results = transcript_rag.retrieve_for_text(
        "redis cache nasil", index_dir=index_dir, top_k=3, embedder=embedder
    )
    assert results
    assert "redis" in results[0]["text"].lower()
    assert results[0]["score"] >= results[-1]["score"]


def test_retrieve_for_text_project_filter(tmp_path):
    root = _projects_root(tmp_path)
    index_dir = tmp_path / "idx"
    embedder = _make_embedder()
    transcript_rag.build_transcript_index(index_dir, projects_root=root, embedder=embedder)
    results = transcript_rag.retrieve_for_text(
        "redis", index_dir=index_dir, project="beta", top_k=5, embedder=embedder
    )
    assert all(r["project"] == "beta" for r in results)


def test_retrieve_for_text_missing_index_returns_empty(tmp_path):
    results = transcript_rag.retrieve_for_text(
        "redis", index_dir=tmp_path / "does-not-exist", embedder=_make_embedder()
    )
    assert results == []
