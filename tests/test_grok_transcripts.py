"""Tests for Grok CLI chat_history.jsonl transcript parsing."""

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from persistent_memory import transcripts


def _line(**kw):
    return json.dumps(kw)


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def grok_chat(tmp_path):
    chat_path = tmp_path / "sessions" / quote("/tmp/proj", safe="") / "sess-1" / "chat_history.jsonl"
    summary = chat_path.parent / "summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        json.dumps({"info": {"id": "sess-1", "cwd": "/tmp/proj"}}),
        encoding="utf-8",
    )
    _write_jsonl(
        chat_path,
        [
            _line(type="system", content="You are Grok."),
            _line(
                type="user",
                content=[{"type": "text", "text": "<user_info>\nignore\n</user_info>"}],
            ),
            _line(
                type="user",
                content=[{"type": "text", "text": "<system-reminder>\ninject\n</system-reminder>"}],
                synthetic_reason="system_reminder",
            ),
            _line(
                type="user",
                content=[{"type": "text", "text": "<user_query>\nyolo mod var mı\n</user_query>"}],
            ),
            _line(
                type="assistant",
                content="Evet, yolo var.",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "read_file",
                        "arguments": json.dumps({"target_file": "/tmp/a.md"}),
                    }
                ],
            ),
            _line(type="tool_result", tool_call_id="call-1", content="file body"),
            _line(type="reasoning", summary=[{"type": "summary_text", "text": "thinking"}]),
            "{ not valid json",
        ],
    )
    return chat_path


def test_detect_grok_by_filename(grok_chat):
    assert transcripts._is_grok_transcript(grok_chat) is True


def test_detect_grok_by_root(monkeypatch, tmp_path):
    monkeypatch.setattr(transcripts, "GROK_ROOT", tmp_path / ".grok")
    path = transcripts.GROK_ROOT / "sessions" / "x" / "chat_history.jsonl"
    assert transcripts._is_grok_transcript(path) is True


def test_claude_path_is_not_grok(tmp_path):
    path = tmp_path / "session.jsonl"
    assert transcripts._is_grok_transcript(path) is False


def test_read_grok_transcript_parses_user_and_assistant(grok_chat):
    messages = transcripts.read_transcript(grok_chat)
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    user_texts = [m.text for m in messages if m.role == "user" and not m.is_tool]
    assert any("yolo mod" in t for t in user_texts)
    assert not any("<system-reminder>" in t for t in user_texts)
    assert not any("<user_info>" in t for t in user_texts)
    assistant_texts = [m.text for m in messages if m.role == "assistant" and not m.is_tool]
    assert any("yolo" in t.lower() for t in assistant_texts)


def test_read_grok_transcript_marks_tool_events(grok_chat):
    messages = transcripts.read_transcript(grok_chat)
    tool_messages = [m for m in messages if m.is_tool]
    assert len(tool_messages) >= 2
    assert any("read_file" in m.text for m in tool_messages)
    assert any("tool_result" in m.text for m in tool_messages)


def test_read_grok_transcript_skips_malformed(grok_chat):
    messages = transcripts.read_transcript(grok_chat)
    assert len(messages) >= 3


def test_first_cwd_from_summary(grok_chat):
    assert transcripts._first_cwd(grok_chat) == "/tmp/proj"
