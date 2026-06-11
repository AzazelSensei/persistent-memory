import io
import json

import pytest

from persistent_memory.hooks import session_start as ss
from persistent_memory.hooks import common


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_emits_recall_block_when_daemon_up(monkeypatch, capsys):
    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s3"})
    monkeypatch.setattr(ss, "is_daemon_healthy", lambda: True)
    monkeypatch.setattr(ss, "fetch_recall_block", lambda project: "## Recall\n- D-0007 accepted")
    assert ss.main() == 0
    out = json.loads(capsys.readouterr().out)
    block = out["hookSpecificOutput"]
    assert block["hookEventName"] == "SessionStart"
    assert "D-0007" in block["additionalContext"]


def test_silent_empty_when_daemon_down(monkeypatch, capsys):
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    monkeypatch.setattr(ss, "is_daemon_healthy", lambda: False)
    called = []
    monkeypatch.setattr(ss, "fetch_recall_block", lambda *a, **k: called.append(1) or "x")
    assert ss.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == ""
    assert called == []


def test_silent_empty_when_recall_raises(monkeypatch, capsys):
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    monkeypatch.setattr(ss, "is_daemon_healthy", lambda: True)

    def boom(project):
        raise RuntimeError("recall failed")

    monkeypatch.setattr(ss, "fetch_recall_block", boom)
    assert ss.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == ""


def test_fetch_recall_block_calls_daemon(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"block": "## Recall\n- L-0003"}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr(ss.httpx, "get", fake_get)
    block = ss.fetch_recall_block(project="pk")
    assert block == "## Recall\n- L-0003"
    assert captured["url"].endswith("/api/recall")
    assert captured["params"]["project"] == "pk"
    assert "cwd" not in captured["params"]
