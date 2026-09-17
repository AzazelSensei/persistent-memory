"""Host detection and Kimi/Grok-specific hook behavior."""

from urllib.parse import quote

from persistent_memory.hooks import common


def test_detect_host_defaults_to_claude():
    assert common.detect_host({}) is common.Host.CLAUDE
    assert common.detect_host({"cwd": "/tmp/p"}) is common.Host.CLAUDE


def test_detect_host_kimi_by_session_dir():
    assert common.detect_host({"session_dir": "/Users/x/.kimi-code/sessions/p/s1"}) is common.Host.KIMI


def test_detect_host_grok_by_env(monkeypatch):
    monkeypatch.setenv("GROK_SESSION_ID", "abc-123")
    assert common.detect_host({"cwd": "/tmp/p"}) is common.Host.GROK


def test_detect_host_grok_by_payload_session_id():
    payload = {"sessionId": "abc-123", "workspaceRoot": "/tmp/p", "hookEventName": "session_start"}
    assert common.detect_host(payload) is common.Host.GROK


def test_state_dir_for_kimi():
    kimi = common.state_dir_for_host(common.Host.KIMI)
    assert ".kimi-code" in str(kimi)
    assert "persistent-memory" in str(kimi)


def test_state_dir_for_grok():
    grok = common.state_dir_for_host(common.Host.GROK)
    assert ".grok" in str(grok)
    assert "persistent-memory" in str(grok)


def test_state_dir_for_claude():
    assert common.state_dir_for_host(common.Host.CLAUDE) == common.DEFAULT_STATE_DIR


def test_extract_prompt_text_from_string():
    assert common.extract_prompt_text({"prompt": "hello"}) == "hello"


def test_extract_prompt_text_from_kimi_content_parts():
    payload = {
        "prompt": [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "world"},
        ]
    }
    assert common.extract_prompt_text(payload) == "Hello world"


def test_extract_prompt_text_from_message():
    payload = {"message": {"role": "user", "content": "via message"}}
    assert common.extract_prompt_text(payload) == "via message"


def test_transcript_path_from_explicit():
    assert common.transcript_path_from_payload({"transcript_path": "/tmp/t.jsonl"}) == "/tmp/t.jsonl"


def test_transcript_path_from_kimi_session_dir(tmp_path):
    session_dir = tmp_path / "s1"
    wire = session_dir / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True)
    wire.write_text("{}", encoding="utf-8")
    assert common.transcript_path_from_payload({"session_dir": str(session_dir)}) == str(wire)


def test_transcript_path_from_grok_session(tmp_path, monkeypatch):
    cwd = "/tmp/proj"
    session_id = "sess-xyz"
    chat = tmp_path / quote(cwd, safe="") / session_id / "chat_history.jsonl"
    chat.parent.mkdir(parents=True)
    chat.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(common, "GROK_SESSIONS_ROOT", tmp_path)
    path = common.transcript_path_from_payload(
        {"sessionId": session_id, "workspaceRoot": cwd, "cwd": cwd}
    )
    assert path == str(chat)


def test_transcript_path_missing_session_dir():
    assert common.transcript_path_from_payload({}) is None


def test_emit_context_grok_writes_sidechannel(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(common.Path, "home", classmethod(lambda cls: tmp_path))
    common.emit_context("recall block", host=common.Host.GROK, event_name="SessionStart")
    side = tmp_path / ".grok" / "persistent-memory" / "last-recall.md"
    assert side.is_file()
    assert "recall block" in side.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "additionalContext" in out
    assert "recall block" in out
