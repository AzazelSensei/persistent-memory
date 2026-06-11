import io
import json
from pathlib import Path

import pytest

from persistent_memory.hooks import common


def test_read_hook_payload_parses_stdin(monkeypatch):
    payload = {"session_id": "s1", "cwd": "/tmp/proj", "hook_event_name": "Stop"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    result = common.read_hook_payload()
    assert result["session_id"] == "s1"
    assert result["cwd"] == "/tmp/proj"


def test_read_hook_payload_empty_returns_empty_dict(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert common.read_hook_payload() == {}


def test_read_hook_payload_invalid_json_returns_empty_dict(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    assert common.read_hook_payload() == {}


def test_project_key_is_stable_hash_of_cwd():
    a = common.build_project_key("/Users/x/Desktop/proj-a")
    b = common.build_project_key("/Users/x/Desktop/proj-a")
    c = common.build_project_key("/Users/x/Desktop/proj-b")
    assert a == b
    assert a != c
    assert len(a) == common.PROJECT_KEY_LENGTH


def test_increment_message_counter_round_trips(tmp_path):
    key = "abc123"
    n1 = common.increment_message_counter(key, state_dir=tmp_path)
    n2 = common.increment_message_counter(key, state_dir=tmp_path)
    assert n1 == 1
    assert n2 == 2
    state_file = tmp_path / f"{key}.json"
    assert state_file.exists()
    assert json.loads(state_file.read_text())["count"] == 2


def test_reset_message_counter_zeroes(tmp_path):
    key = "abc123"
    common.increment_message_counter(key, state_dir=tmp_path)
    common.increment_message_counter(key, state_dir=tmp_path)
    common.reset_message_counter(key, state_dir=tmp_path)
    assert common.read_message_counter(key, state_dir=tmp_path) == 0


def test_read_message_counter_missing_returns_zero(tmp_path):
    assert common.read_message_counter("nope", state_dir=tmp_path) == 0


def test_post_daemon_signal_returns_false_when_daemon_down(monkeypatch):
    def fail_post(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(common.httpx, "post", fail_post)
    assert common.post_daemon_signal("/api/extract", {"project": "p"}) is False


def test_is_daemon_healthy_false_on_error(monkeypatch):
    def fail_get(*args, **kwargs):
        raise OSError("no daemon")

    monkeypatch.setattr(common.httpx, "get", fail_get)
    assert common.is_daemon_healthy() is False


def test_post_daemon_signal_sends_token_header(monkeypatch, tmp_path):
    from persistent_memory.daemon.token import token_path

    path = token_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("secrettoken", encoding="utf-8")
    monkeypatch.setattr(common, "default_records_dir", lambda: tmp_path)

    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers or {}
        return FakeResp()

    monkeypatch.setattr(common.httpx, "post", fake_post)
    assert common.post_daemon_signal("/api/extract", {"project": "p"}) is True
    assert captured["headers"].get("X-PM-Token") == "secrettoken"


def test_post_daemon_signal_no_crash_when_token_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "default_records_dir", lambda: tmp_path)

    class FakeResp:
        status_code = 200

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers or {}
        return FakeResp()

    monkeypatch.setattr(common.httpx, "post", fake_post)
    assert common.post_daemon_signal("/api/extract", {"project": "p"}) is True
    assert "X-PM-Token" not in captured["headers"]
