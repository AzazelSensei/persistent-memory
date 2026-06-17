"""Tests for Kimi Code CLI wire.jsonl transcript parsing."""

import json

import pytest

from persistent_memory import transcripts


def _line(**kw):
    return json.dumps(kw)


def _write_wire(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def kimi_wire(tmp_path):
    wire_path = tmp_path / "session-abc" / "agents" / "main" / "wire.jsonl"
    _write_wire(
        wire_path,
        [
            _line(type="metadata", protocol_version="1.4", created_at=1781691552269),
            _line(
                type="context.append_message",
                time=1781691600697,
                message={
                    "role": "user",
                    "content": [{"type": "text", "text": "skiller var mı?"}],
                    "toolCalls": [],
                    "origin": {"kind": "user"},
                },
            ),
            _line(
                type="context.append_message",
                time=1781691600698,
                message={
                    "role": "user",
                    "content": [{"type": "text", "text": "<system-reminder>\nignore me\n</system-reminder>"}],
                    "toolCalls": [],
                    "origin": {"kind": "injection", "variant": "todo_list_reminder"},
                },
            ),
            _line(
                type="context.append_loop_event",
                time=1781691609761,
                event={
                    "type": "content.part",
                    "part": {"type": "think", "think": "internal reasoning"},
                },
            ),
            _line(
                type="context.append_loop_event",
                time=1781691609762,
                event={
                    "type": "content.part",
                    "part": {"type": "text", "text": "Şu anda listede sadece bir skill görünüyor."},
                },
            ),
            _line(
                type="context.append_loop_event",
                time=1781691670546,
                event={
                    "type": "tool.call",
                    "toolCallId": "tool_abc",
                    "name": "Glob",
                    "args": {"pattern": "**/SKILL.md"},
                },
            ),
            _line(
                type="context.append_loop_event",
                time=1781691674617,
                event={
                    "type": "tool.result",
                    "parentUuid": "tool_abc",
                    "toolCallId": "tool_abc",
                    "result": {"output": "No matches found"},
                },
            ),
            "{ this is not valid json",
        ],
    )
    return wire_path


def test_detect_kimi_by_wire_filename(kimi_wire):
    assert transcripts._is_kimi_transcript(kimi_wire) is True


def test_detect_kimi_by_kimi_root():
    path = transcripts.KIMI_ROOT / "sessions" / "some" / "wire.jsonl"
    assert transcripts._is_kimi_transcript(path) is True


def test_claude_path_is_not_kimi(tmp_path):
    path = tmp_path / "session.jsonl"
    assert transcripts._is_kimi_transcript(path) is False


def test_read_kimi_transcript_parses_user_and_assistant(kimi_wire):
    messages = transcripts.read_transcript(kimi_wire)
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    user_texts = [m.text for m in messages if m.role == "user" and not m.is_tool]
    assert "skiller var mı?" in user_texts
    assert "<system-reminder>" not in " ".join(user_texts)
    assistant_texts = [m.text for m in messages if m.role == "assistant" and not m.is_tool]
    assert "Şu anda listede sadece bir skill görünüyor." in assistant_texts
    assert "internal reasoning" not in " ".join(assistant_texts)


def test_read_kimi_transcript_marks_tool_events(kimi_wire):
    messages = transcripts.read_transcript(kimi_wire)
    tool_messages = [m for m in messages if m.is_tool]
    assert len(tool_messages) == 2
    assert any("Glob" in m.text for m in tool_messages)
    assert any("tool_result" in m.text for m in tool_messages)


def test_read_kimi_transcript_timestamps_are_iso(kimi_wire):
    messages = transcripts.read_transcript(kimi_wire)
    for message in messages:
        assert message.timestamp is not None
        assert "T" in message.timestamp


def test_read_kimi_transcript_skips_malformed(kimi_wire):
    messages = transcripts.read_transcript(kimi_wire)
    assert len(messages) >= 4
