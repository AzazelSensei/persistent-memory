"""Tests for the PreToolUse model-guard hook."""

import io
import os
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


# ---------------------------------------------------------------------------
# Workflow tripwire: the model lives inside the
# script body, so the guard only checks whether ANY pin is present. Unreadable
# scripts fail OPEN — this guard exists to catch forgetting, not an attacker,
# and a false deny would push the user to disable the whole guard.
# ---------------------------------------------------------------------------

WF_WITH_PIN = """
export const meta = { name: 'x', description: 'd' }
const r = await agent('do the thing', { model: 'sonnet' })
"""

WF_WITHOUT_PIN = """
export const meta = { name: 'x', description: 'd' }
const r = await agent('do the thing', { schema: S })
"""

WF_NO_AGENT = """
export const meta = { name: 'x', description: 'd' }
log('nothing dispatched here')
"""


def test_workflow_inline_script_without_model_denies(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"script": WF_WITHOUT_PIN},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    decision = _deny_output(capsys)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "agent()" in decision["permissionDecisionReason"]


def test_workflow_inline_script_with_model_allows(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"script": WF_WITH_PIN},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_workflow_script_without_agent_calls_allows(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"script": WF_NO_AGENT},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_workflow_script_path_without_model_denies(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    script = tmp_path / "wf.js"
    script.write_text(WF_WITHOUT_PIN, encoding="utf-8")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"scriptPath": str(script)},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    decision = _deny_output(capsys)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"


def test_workflow_script_path_with_model_allows(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    script = tmp_path / "wf.js"
    script.write_text(WF_WITH_PIN, encoding="utf-8")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"scriptPath": str(script)},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_workflow_unreadable_script_path_fails_open(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"scriptPath": str(tmp_path / "yok.js")},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_workflow_oversized_script_path_fails_open(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    script = tmp_path / "big.js"
    script.write_text(WF_WITHOUT_PIN + "\n" + "x" * (ptu.SCRIPT_MAX_BYTES + 1), encoding="utf-8")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"scriptPath": str(script)},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_workflow_named_run_without_script_fails_open(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"name": "saved-workflow"},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    assert capsys.readouterr().out == ""


def test_workflow_deny_reason_rejects_the_harness_omit_advice(monkeypatch, capsys):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {
        "tool_name": "Workflow",
        "tool_input": {"script": WF_WITHOUT_PIN},
        "cwd": "/tmp/p",
    })
    assert ptu.main() == 0
    reason = _deny_output(capsys)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "opts.model" in reason
    assert "omit" in reason.lower()


# ---------------------------------------------------------------------------
# Tripwire defects found by adversarial verification (2026-07-27).
# ---------------------------------------------------------------------------

WF_META_PIN_ONLY = """
export const meta = {
  name: 'x',
  description: 'd',
  phases: [{ title: 'A', detail: 'd', model: 'opus' }],
}
const r = await agent('do the thing', { schema: S })
"""

WF_QUOTED_PIN = """
export const meta = { name: 'x', description: 'd' }
const r = await agent('do the thing', { "model": "sonnet" })
"""

WF_SINGLE_QUOTED_PIN = """
export const meta = { name: 'x', description: 'd' }
const r = await agent('do the thing', { 'model': 'sonnet' })
"""

WF_SHORTHAND_PIN = """
export const meta = { name: 'x', description: 'd' }
const model = 'sonnet'
const r = await agent('do the thing', { label, model })
"""

WF_SCHEMA_MODEL_ONLY = """
export const meta = { name: 'x', description: 'd' }
const S = { type: 'object', properties: { model: { type: 'string' } } }
const r = await agent('do the thing', { schema: S })
"""


def _workflow_verdict(monkeypatch, capsys, tool_input) -> str:
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {"tool_name": "Workflow", "tool_input": tool_input, "cwd": "/tmp/p"})
    assert ptu.main() == 0
    return "deny" if capsys.readouterr().out else "allow"


def test_meta_phase_model_does_not_count_as_a_pin(monkeypatch, capsys):
    assert _workflow_verdict(monkeypatch, capsys, {"script": WF_META_PIN_ONLY}) == "deny"


def test_schema_property_named_model_does_not_count_as_a_pin(monkeypatch, capsys):
    assert _workflow_verdict(monkeypatch, capsys, {"script": WF_SCHEMA_MODEL_ONLY}) == "deny"


@pytest.mark.parametrize(
    "script",
    [WF_QUOTED_PIN, WF_SINGLE_QUOTED_PIN, WF_SHORTHAND_PIN],
    ids=["double-quoted", "single-quoted", "shorthand"],
)
def test_quoted_and_shorthand_pins_are_accepted(monkeypatch, capsys, script):
    assert _workflow_verdict(monkeypatch, capsys, {"script": script}) == "allow"


def test_blocking_script_path_fails_open_without_hanging(monkeypatch, capsys, tmp_path):
    fifo = tmp_path / "fifo.js"
    os.mkfifo(fifo)
    assert _workflow_verdict(monkeypatch, capsys, {"scriptPath": str(fifo)}) == "allow"


def test_directory_script_path_fails_open(monkeypatch, capsys, tmp_path):
    assert _workflow_verdict(monkeypatch, capsys, {"scriptPath": str(tmp_path)}) == "allow"


@pytest.mark.parametrize("tool_input", [["x"], "script", 42], ids=["list", "str", "int"])
@pytest.mark.parametrize("tool_name", ["Workflow", "Agent", "Task"])
def test_non_dict_tool_input_never_crashes(monkeypatch, capsys, tool_name, tool_input):
    monkeypatch.setattr(ptu, "fetch_memory_recall", lambda q, project: "")
    _feed(monkeypatch, {"tool_name": tool_name, "tool_input": tool_input, "cwd": "/tmp/p"})
    assert ptu.main() == 0
