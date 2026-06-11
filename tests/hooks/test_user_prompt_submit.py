import io
import json

import pytest

from persistent_memory.hooks import user_prompt_submit as ups
from persistent_memory.hooks import common


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_no_trigger_before_interval(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "post_daemon_signal", lambda *a, **k: sent.append(a) or True)
    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
    code = ups.main()
    assert code == 0
    assert sent == []


def test_triggers_extract_at_interval(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)
    key = common.build_project_key("/tmp/p")
    for _ in range(ups.EXTRACT_TRIGGER_INTERVAL - 1):
        _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
        ups.main()
    assert sent == []
    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s1"})
    ups.main()
    assert len(sent) == 1
    endpoint, body = sent[0]
    assert endpoint == "/api/extract"
    assert body["project"] == common.project_name("/tmp/p")
    assert body["cwd"] == "/tmp/p"
    assert common.read_message_counter(key, state_dir=tmp_path) == 0


def test_exit_zero_when_daemon_down(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "post_daemon_signal", lambda *a, **k: False)
    for _ in range(ups.EXTRACT_TRIGGER_INTERVAL):
        _feed(monkeypatch, {"cwd": "/tmp/p"})
        assert ups.main() == 0


def test_missing_cwd_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "post_daemon_signal", lambda *a, **k: True)
    _feed(monkeypatch, {})
    assert ups.main() == 0
