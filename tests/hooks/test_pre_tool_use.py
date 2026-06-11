"""Tests for the PreToolUse model-guard hook."""

import io
import json

import httpx
import pytest

from persistent_memory.hooks import pre_tool_use as ptu
from persistent_memory.hooks import common


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def _deny_output(capsys) -> dict:
    raw = capsys.readouterr().out
    assert raw, "expected stdout output"
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Core deny / allow decisions
# ---------------------------------------------------------------------------

def test_agent_without_model_emits_deny(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {"tool_name": "Agent", "tool_input": {}, "cwd": "/tmp/p"})
    assert ptu.main() == 0
    out = _deny_output(capsys)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    reason = decision["permissionDecisionReason"]
    assert "sonnet" in reason
    assert "haiku" in reason


def test_agent_with_model_allows_silently(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Agent",
        "tool_input": {"model": "claude-sonnet-4-5"},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_bash_tool_allows_silently(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {"tool_name": "Bash", "tool_input": {}, "cwd": "/tmp/p"})
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_task_alias_without_model_emits_deny(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {"tool_name": "Task", "tool_input": {}, "cwd": "/tmp/p"})
    assert ptu.main() == 0
    out = _deny_output(capsys)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_disable_env_var_allows_silently(monkeypatch, capsys):
    monkeypatch.setenv("PM_DISABLE_MODEL_GUARD", "1")
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {"tool_name": "Agent", "tool_input": {}, "cwd": "/tmp/p"})
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_empty_model_string_triggers_deny(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Agent",
        "tool_input": {"model": ""},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    out = _deny_output(capsys)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# ---------------------------------------------------------------------------
# Daemon integration (memory enrichment)
# ---------------------------------------------------------------------------

def test_daemon_down_still_emits_deny(monkeypatch, capsys):
    def raise_http(q, project):
        raise httpx.ConnectError("daemon down")

    monkeypatch.setattr(ptu, "fetch_memory_recall", raise_http)
    _feed(monkeypatch, {"tool_name": "Agent", "tool_input": {}, "cwd": "/tmp/p"})
    assert ptu.main() == 0
    out = _deny_output(capsys)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    # reason still mentions the rule
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "sonnet" in reason


def test_daemon_returns_block_appended_to_reason(monkeypatch, capsys):
    monkeypatch.setattr(
        ptu, "fetch_memory_recall",
        lambda q, project: "📌 Related: always pin subagent model to avoid flagship cost.",
    )
    _feed(monkeypatch, {"tool_name": "Agent", "tool_input": {}, "cwd": "/tmp/p"})
    assert ptu.main() == 0
    out = _deny_output(capsys)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "always pin subagent model" in reason


# ---------------------------------------------------------------------------
# fetch_memory_recall unit tests
# ---------------------------------------------------------------------------

def test_fetch_memory_recall_calls_daemon(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"block": "📌 memory block"}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(ptu.httpx, "get", fake_get)
    block = ptu.fetch_memory_recall("subagent model", "myproject")
    assert block == "📌 memory block"
    assert captured["url"].endswith("/api/prompt-recall")
    assert captured["params"]["q"] == "subagent model"
    assert captured["params"]["project"] == "myproject"
    assert captured["timeout"] == ptu.RECALL_HTTP_TIMEOUT_SECONDS


def test_fetch_memory_recall_empty_on_non_200(monkeypatch):
    class FakeResp:
        status_code = 503
        def json(self):
            return {"block": "should-not-be-used"}

    monkeypatch.setattr(ptu.httpx, "get", lambda url, params=None, timeout=None: FakeResp())
    assert ptu.fetch_memory_recall("x", "p") == ""
