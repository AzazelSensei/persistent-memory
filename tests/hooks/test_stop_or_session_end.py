import io
import json

from persistent_memory.hooks import stop_or_session_end as se
from persistent_memory.hooks import common


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_flush_when_pending_messages(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(se, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)
    key = common.build_project_key("/tmp/p")
    common.increment_message_counter(key, state_dir=tmp_path)
    common.increment_message_counter(key, state_dir=tmp_path)
    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s9"})
    assert se.main() == 0
    assert len(sent) == 1
    endpoint, body = sent[0]
    assert endpoint == "/api/extract"
    assert body["flush"] is True
    assert body["project"] == common.project_name("/tmp/p")
    assert common.read_message_counter(key, state_dir=tmp_path) == 0


def test_no_flush_when_counter_zero(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(se, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    assert se.main() == 0
    assert sent == []


def test_exit_zero_when_daemon_down(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(se, "post_daemon_signal", lambda *a, **k: False)
    key = common.build_project_key("/tmp/p")
    common.increment_message_counter(key, state_dir=tmp_path)
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    assert se.main() == 0
    assert common.read_message_counter(key, state_dir=tmp_path) == 0
