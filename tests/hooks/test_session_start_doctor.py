import io
import json

import pytest

from persistent_memory.hooks import session_start as ss


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_warning_prepended_when_critical_missing(monkeypatch, capsys):
    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
    monkeypatch.setattr(ss, "is_daemon_healthy", lambda: True)
    monkeypatch.setattr(ss, "fetch_recall_block", lambda project: "## Recall\n- D-1")
    monkeypatch.setattr(ss, "detect_missing_critical", lambda: ["ollama-server"])
    assert ss.main() == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert ctx.splitlines()[0].startswith("⚠️")
    assert "doctor" in ctx
    assert "D-1" in ctx


def test_no_warning_when_all_present(monkeypatch, capsys):
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    monkeypatch.setattr(ss, "is_daemon_healthy", lambda: True)
    monkeypatch.setattr(ss, "fetch_recall_block", lambda project: "## Recall\n- D-1")
    monkeypatch.setattr(ss, "detect_missing_critical", lambda: [])
    assert ss.main() == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "⚠️" not in ctx
    assert "D-1" in ctx


def test_detection_failure_degrades_silently(monkeypatch, capsys):
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    monkeypatch.setattr(ss, "is_daemon_healthy", lambda: True)
    monkeypatch.setattr(ss, "fetch_recall_block", lambda project: "## Recall\n- D-1")

    def boom():
        raise RuntimeError("detect failed")

    monkeypatch.setattr(ss, "detect_missing_critical", boom)
    assert ss.main() == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "D-1" in ctx
    assert "⚠️" not in ctx


def test_warning_emitted_even_when_daemon_down(monkeypatch, capsys):
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    monkeypatch.setattr(ss, "is_daemon_healthy", lambda: False)
    monkeypatch.setattr(ss, "detect_missing_critical", lambda: ["venv"])
    assert ss.main() == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith("⚠️")
    assert "venv" in ctx
