"""TDD: hook payloads include branch field when available."""

import io
import json
from unittest.mock import patch

import pytest

from persistent_memory.hooks import common
from persistent_memory.hooks import user_prompt_submit as ups
from persistent_memory.hooks import stop_or_session_end as sse
from persistent_memory.hooks import pre_compact as pc


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


# ---------------------------------------------------------------------------
# user_prompt_submit: extract signal body includes branch
# ---------------------------------------------------------------------------

def test_user_prompt_submit_extract_signal_has_branch(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)

    # Patch derive_project_and_branch to simulate a worktree cwd
    monkeypatch.setattr(
        common,
        "derive_project_and_branch",
        lambda cwd: ("BlackHoleLabs", "faz1-backend"),
    )

    key = common.build_project_key("/tmp/p")
    for _ in range(ups.EXTRACT_TRIGGER_INTERVAL - 1):
        _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
        ups.main()

    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
    ups.main()

    assert len(sent) == 1
    endpoint, body = sent[0]
    assert body["project"] == "BlackHoleLabs"
    assert body.get("branch") == "faz1-backend"


def test_user_prompt_submit_extract_signal_no_branch_when_none(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)

    monkeypatch.setattr(
        common,
        "derive_project_and_branch",
        lambda cwd: ("myproject", None),
    )

    key = common.build_project_key("/tmp/p")
    for _ in range(ups.EXTRACT_TRIGGER_INTERVAL - 1):
        _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
        ups.main()

    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
    ups.main()

    assert len(sent) == 1
    _, body = sent[0]
    assert body["project"] == "myproject"
    # branch key absent or None — both acceptable
    assert body.get("branch") is None


# ---------------------------------------------------------------------------
# stop_or_session_end: flush signal includes branch
# ---------------------------------------------------------------------------

def test_stop_hook_flush_signal_has_branch(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(sse, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)

    monkeypatch.setattr(
        common,
        "derive_project_and_branch",
        lambda cwd: ("BlackHoleLabs", "faz2-auth"),
    )

    key = common.build_project_key("/tmp/p")
    common.increment_message_counter(key, state_dir=tmp_path)

    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
    code = sse.main()

    assert code == 0
    assert len(sent) == 1
    _, body = sent[0]
    assert body["project"] == "BlackHoleLabs"
    assert body.get("branch") == "faz2-auth"


# ---------------------------------------------------------------------------
# pre_compact: flush signal includes branch
# ---------------------------------------------------------------------------

def test_pre_compact_signal_has_branch(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(pc, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)

    monkeypatch.setattr(
        common,
        "derive_project_and_branch",
        lambda cwd: ("BlackHoleLabs", "hotfix-99"),
    )

    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
    code = pc.main()

    assert code == 0
    assert len(sent) == 1
    _, body = sent[0]
    assert body["project"] == "BlackHoleLabs"
    assert body.get("branch") == "hotfix-99"
