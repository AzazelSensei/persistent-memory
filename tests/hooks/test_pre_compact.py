import io
import json

from persistent_memory.hooks import pre_compact as pc
from persistent_memory.hooks import common


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_always_flushes_on_compact(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(pc, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)
    _feed(monkeypatch, {"cwd": "/tmp/p", "session_id": "s2"})
    assert pc.main() == 0
    assert len(sent) == 1
    endpoint, body = sent[0]
    assert endpoint == "/api/extract"
    assert body["flush"] is True
    assert body["reason"] == "pre_compact"


def test_resets_counter_after_flush(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(pc, "post_daemon_signal", lambda *a, **k: True)
    key = common.build_project_key("/tmp/p")
    common.increment_message_counter(key, state_dir=tmp_path)
    common.increment_message_counter(key, state_dir=tmp_path)
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    pc.main()
    assert common.read_message_counter(key, state_dir=tmp_path) == 0


def test_sends_project_name_not_hash(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(pc, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)
    _feed(monkeypatch, {"cwd": "/tmp/proj-x", "session_id": "s9"})
    assert pc.main() == 0
    assert sent[0][1]["project"] == "proj-x"


def test_exit_zero_when_daemon_down(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(pc, "post_daemon_signal", lambda *a, **k: False)
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    assert pc.main() == 0
