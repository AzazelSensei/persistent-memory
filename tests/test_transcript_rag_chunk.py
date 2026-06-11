import json

import pytest

from persistent_memory import transcript_rag


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


def _assistant_tool(cwd, name, ts, **inp):
    return _line(
        type="assistant",
        cwd=cwd,
        timestamp=ts,
        message={
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": name, "input": inp}],
        },
    )


def _tool_result(cwd, ts):
    return _line(
        type="user",
        cwd=cwd,
        timestamp=ts,
        message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    )


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


CWD = "/Users/dev/Desktop/project-alpha"
PROJECT_DIRNAME = "-Users-dev-Desktop-project-alpha"
SESSION_A = "aaaaaaaa-1111-1111-1111-111111111111"


@pytest.fixture
def project_dir(tmp_path):
    pdir = tmp_path / "projects" / PROJECT_DIRNAME
    _write(
        pdir / f"{SESSION_A}.jsonl",
        [
            _user(CWD, "redis cache ekleyelim mi?", "2026-06-01T12:00:00.000Z"),
            _assistant(CWD, "evet, N+1 sorunu icin uygun.", "2026-06-01T12:00:05.000Z"),
            _user(CWD, "peki TTL ne olsun?", "2026-06-01T12:00:10.000Z"),
            _assistant(CWD, "300 saniye baslangic icin yeterli.", "2026-06-01T12:00:12.000Z"),
        ],
    )
    return pdir


def test_chunk_project_produces_role_tagged_chunks(project_dir):
    chunks = transcript_rag.chunk_project(project_dir)
    assert chunks
    combined = "\n".join(c.text for c in chunks)
    assert "redis cache ekleyelim mi?" in combined
    assert "user" in combined.lower()
    assert "assistant" in combined.lower()


def test_chunk_project_sets_session_and_project_metadata(project_dir):
    chunks = transcript_rag.chunk_project(project_dir)
    assert all(c.session_id == SESSION_A for c in chunks)
    assert all(c.project == "project-alpha" for c in chunks)
    assert all(isinstance(c.ordinal, int) for c in chunks)
    assert chunks[0].timestamp == "2026-06-01T12:00:00.000Z"


def test_chunk_project_window_groups_messages(project_dir):
    chunks = transcript_rag.chunk_project(project_dir, window=2)
    assert len(chunks) == 2
    assert chunks[0].ordinal == 0
    assert chunks[1].ordinal == 1
    assert "redis cache ekleyelim mi?" in chunks[0].text
    assert "TTL" in chunks[1].text


def test_chunk_project_respects_max_chars(project_dir):
    chunks = transcript_rag.chunk_project(project_dir, window=6, max_chars=60)
    assert all(len(c.text) <= 60 for c in chunks)


def test_chunk_project_skips_tool_noise_only_chunks(tmp_path):
    pdir = tmp_path / "projects" / PROJECT_DIRNAME
    _write(
        pdir / f"{SESSION_A}.jsonl",
        [
            _assistant_tool(CWD, "Bash", "2026-06-01T12:00:00.000Z", command="ls"),
            _tool_result(CWD, "2026-06-01T12:00:01.000Z"),
            _assistant_tool(CWD, "Read", "2026-06-01T12:00:02.000Z", file_path="/x"),
        ],
    )
    chunks = transcript_rag.chunk_project(pdir, window=6)
    assert chunks == []


def test_chunk_project_empty_dir_returns_empty(tmp_path):
    assert transcript_rag.chunk_project(tmp_path / "nope") == []
