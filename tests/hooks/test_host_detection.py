"""Host detection and Kimi-specific hook behavior."""

from persistent_memory.hooks import common


def test_detect_host_defaults_to_claude():
    assert common.detect_host({}) is common.Host.CLAUDE
    assert common.detect_host({"cwd": "/tmp/p"}) is common.Host.CLAUDE


def test_detect_host_kimi_by_session_dir():
    assert common.detect_host({"session_dir": "/Users/x/.kimi-code/sessions/p/s1"}) is common.Host.KIMI


def test_state_dir_for_kimi():
    kimi = common.state_dir_for_host(common.Host.KIMI)
    assert ".kimi-code" in str(kimi)
    assert "persistent-memory" in str(kimi)


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


def test_transcript_path_missing_session_dir():
    assert common.transcript_path_from_payload({}) is None
