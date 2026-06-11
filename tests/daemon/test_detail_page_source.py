import json
import textwrap

import httpx
from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.embeddings import OllamaEmbedder
from persistent_memory.transcript_rag import Chunk, TranscriptRagIndex

EMBED_DIM = 8


def _write_record(directory, rec_id, *, project="alpha", body, status="proposed"):
    directory.mkdir(parents=True, exist_ok=True)
    front = textwrap.dedent(f"""\
        ---
        id: {rec_id}
        type: decision
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


def _make_embedder():
    def handler(request):
        payload = json.loads(request.content)
        out = []
        for t in payload["input"]:
            vec = [0.0] * EMBED_DIM
            vec[1 if "redis" in t.lower() else 0] = 1.0
            out.append(vec)
        return httpx.Response(200, json={"embeddings": out})

    return OllamaEmbedder(transport=httpx.MockTransport(handler))


def _build_index(index_dir, *, text, project="alpha", session="sess-redis"):
    index = TranscriptRagIndex()
    index.add_chunks(
        [
            Chunk(
                project=project,
                session_id=session,
                text=text,
                timestamp="2026-06-01T12:00:00.000Z",
                ordinal=0,
            )
        ],
        _make_embedder(),
    )
    index.save(index_dir)


def _app(tmp_path, monkeypatch, index_dir=None):
    monkeypatch.setattr("persistent_memory.transcript_rag.OllamaEmbedder", _make_embedder)
    cfg = DaemonConfig(
        records_dir=tmp_path, watch_enabled=False, transcript_index_dir=index_dir
    )
    return create_app(records_dir=tmp_path, config=cfg)


def test_detail_page_renders_kaynak_section_with_passage(tmp_path, monkeypatch):
    _write_record(
        tmp_path / "decisions",
        "D-0001",
        project="alpha",
        body="# Redis karari\n\n## Karar\nredis ekledik\n",
    )
    index_dir = tmp_path / "idx"
    _build_index(index_dir, text="[user] redis cache ekleyelim\n[assistant] evet")
    client = TestClient(_app(tmp_path, monkeypatch, index_dir=index_dir))
    html = client.get("/records/D-0001").text
    assert "Source" in html
    assert "redis cache ekleyelim" in html
    assert "sess-red" in html


def test_detail_page_kaynak_escapes_script_passage(tmp_path, monkeypatch):
    _write_record(
        tmp_path / "decisions",
        "D-0001",
        project="alpha",
        body="# Redis karari\n\n## Karar\nredis ekledik\n",
    )
    index_dir = tmp_path / "idx"
    _build_index(index_dir, text="[user] redis <script>alert(1)</script>")
    client = TestClient(_app(tmp_path, monkeypatch, index_dir=index_dir))
    html = client.get("/records/D-0001").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_detail_page_kaynak_empty_note_when_no_index(tmp_path, monkeypatch):
    _write_record(
        tmp_path / "decisions",
        "D-0001",
        project="alpha",
        body="# Baslik\n\n## Karar\nx\n",
    )
    missing = tmp_path / "no-such-index"
    client = TestClient(_app(tmp_path, monkeypatch, index_dir=missing))
    html = client.get("/records/D-0001").text
    assert "Source" in html
    assert "index not built yet" in html
