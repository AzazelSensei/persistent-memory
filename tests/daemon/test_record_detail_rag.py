import json
import textwrap

import httpx

from persistent_memory.daemon import services
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.embeddings import OllamaEmbedder
from persistent_memory.transcript_rag import Chunk, TranscriptRagIndex

EMBED_DIM = 8


def _write_record(directory, rec_id, rec_type, *, project="alpha", body, status="proposed"):
    directory.mkdir(parents=True, exist_ok=True)
    front = textwrap.dedent(f"""\
        ---
        id: {rec_id}
        type: {rec_type}
        status: {status}
        date: '2026-06-02'
        project: {project}
        provenance:
          session: s
          cwd: /tmp
          agent: claude-opus-4-8
        tags: []
        supersedes: []
        superseded-by: []
        salience: 0.5
        ---
        """)
    (directory / f"{rec_id}.md").write_text(front + body, encoding="utf-8")


def _keyword_axis(text):
    return 1 if "redis" in text.lower() else 0


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


def _build_index(index_dir, project="alpha"):
    embedder = _make_embedder()
    index = TranscriptRagIndex()
    index.add_chunks(
        [
            Chunk(
                project=project,
                session_id="sess-redis",
                text="[user] redis cache ekleyelim mi?\n[assistant] evet uygun",
                timestamp="2026-06-01T12:00:00.000Z",
                ordinal=0,
            ),
            Chunk(
                project=project,
                session_id="sess-other",
                text="[user] hava nasil",
                timestamp="2026-06-01T13:00:00.000Z",
                ordinal=0,
            ),
        ],
        embedder,
    )
    index.save(index_dir)


def test_record_detail_includes_source_passages(tmp_path, monkeypatch):
    _write_record(
        tmp_path / "decisions",
        "D-0001",
        "decision",
        project="alpha",
        body="# Redis cache karari\n\n## Karar\nredis ekledik\n",
    )
    index_dir = tmp_path / ".pm-index" / "transcripts"
    _build_index(index_dir)
    monkeypatch.setattr("persistent_memory.transcript_rag.OllamaEmbedder", _make_embedder)

    detail = services.record_detail(tmp_path, "D-0001")
    assert "source_passages" in detail
    assert detail["source_passages"]
    assert "redis" in detail["source_passages"][0]["text"].lower()
    assert detail["source_passages"][0]["session_id"] == "sess-redis"


def test_record_detail_source_passages_empty_when_no_index(tmp_path):
    _write_record(
        tmp_path / "decisions",
        "D-0001",
        "decision",
        body="# Baslik\n\n## Karar\nx\n",
    )
    detail = services.record_detail(tmp_path, "D-0001")
    assert detail["source_passages"] == []


def test_record_detail_source_passages_empty_when_ollama_down(tmp_path, monkeypatch):
    _write_record(
        tmp_path / "decisions",
        "D-0001",
        "decision",
        body="# Baslik\n\n## Karar\nx\n",
    )
    index_dir = tmp_path / ".pm-index" / "transcripts"
    _build_index(index_dir)

    def _broken_embedder():
        def handler(request):
            raise httpx.ConnectError("down")

        return OllamaEmbedder(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("persistent_memory.embeddings.time.sleep", lambda _: None)
    monkeypatch.setattr("persistent_memory.transcript_rag.OllamaEmbedder", _broken_embedder)
    detail = services.record_detail(tmp_path, "D-0001")
    assert detail["source_passages"] == []


def test_daemon_config_has_transcript_index_dir(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path)
    assert cfg.transcript_index_path == tmp_path / ".pm-index" / "transcripts"


def test_daemon_config_transcript_index_dir_override(tmp_path):
    override = tmp_path / "custom-idx"
    cfg = DaemonConfig(records_dir=tmp_path, transcript_index_dir=override)
    assert cfg.transcript_index_path == override
