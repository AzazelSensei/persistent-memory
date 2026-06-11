import io
import json

import httpx

from persistent_memory.hooks import common
from persistent_memory.hooks import user_prompt_submit as ups


def _feed(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def _isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "post_daemon_signal", lambda *a, **k: True)


def test_injects_recall_block_as_additional_context(monkeypatch, tmp_path, capsys):
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ups, "fetch_prompt_recall_block",
        lambda prompt, project: "📌 İlgili geçmiş hafıza:\n- [D-0007] batch fetch (project-alpha): tek JOIN",
    )
    _feed(monkeypatch, {"cwd": "/tmp/p", "prompt": "N+1 sorgu nasil cozulur"})
    assert ups.main() == 0
    out = json.loads(capsys.readouterr().out)
    block = out["hookSpecificOutput"]
    assert block["hookEventName"] == "UserPromptSubmit"
    assert "D-0007" in block["additionalContext"]


def test_passes_prompt_and_project_to_recall(monkeypatch, tmp_path, capsys):
    _isolate_state(monkeypatch, tmp_path)
    captured = {}

    def fake_fetch(prompt, project):
        captured.update(prompt=prompt, project=project)
        return ""

    monkeypatch.setattr(ups, "fetch_prompt_recall_block", fake_fetch)
    _feed(monkeypatch, {"cwd": "/tmp/p", "prompt": "merhaba"})
    ups.main()
    assert captured["prompt"] == "merhaba"
    assert captured["project"] == common.project_name("/tmp/p")


def test_no_output_when_block_empty(monkeypatch, tmp_path, capsys):
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(ups, "fetch_prompt_recall_block", lambda prompt, project: "")
    _feed(monkeypatch, {"cwd": "/tmp/p", "prompt": "selam"})
    assert ups.main() == 0
    assert capsys.readouterr().out == ""


def test_no_output_and_exit_zero_when_recall_raises(monkeypatch, tmp_path, capsys):
    _isolate_state(monkeypatch, tmp_path)

    def boom(prompt, project):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(ups, "fetch_prompt_recall_block", boom)
    _feed(monkeypatch, {"cwd": "/tmp/p", "prompt": "selam"})
    assert ups.main() == 0
    assert capsys.readouterr().out == ""


def test_no_recall_when_prompt_missing(monkeypatch, tmp_path, capsys):
    _isolate_state(monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(
        ups, "fetch_prompt_recall_block", lambda prompt, project: called.append(1) or "x"
    )
    _feed(monkeypatch, {"cwd": "/tmp/p"})
    assert ups.main() == 0
    assert called == []
    assert capsys.readouterr().out == ""


def test_counter_increments_alongside_recall(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(ups, "fetch_prompt_recall_block", lambda prompt, project: "")
    key = common.build_project_key("/tmp/p")
    _feed(monkeypatch, {"cwd": "/tmp/p", "prompt": "ilk mesaj"})
    ups.main()
    assert common.read_message_counter(key, state_dir=tmp_path) == 1


def test_extraction_still_triggers_on_fifth_message(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "DEFAULT_STATE_DIR", tmp_path)
    monkeypatch.setattr(ups, "fetch_prompt_recall_block", lambda prompt, project: "")
    sent = []
    monkeypatch.setattr(ups, "post_daemon_signal", lambda ep, body: sent.append((ep, body)) or True)
    key = common.build_project_key("/tmp/p")
    for _ in range(ups.EXTRACT_TRIGGER_INTERVAL):
        _feed(monkeypatch, {"cwd": "/tmp/p", "prompt": "x"})
        ups.main()
    assert len(sent) == 1
    assert sent[0][0] == "/api/extract"
    assert common.read_message_counter(key, state_dir=tmp_path) == 0


def test_fetch_prompt_recall_block_calls_daemon(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"block": "📌\n- L-0003"}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(ups.httpx, "get", fake_get)
    block = ups.fetch_prompt_recall_block(prompt="silme dogrula", project="pk")
    assert block == "📌\n- L-0003"
    assert captured["url"].endswith("/api/prompt-recall")
    assert captured["params"]["q"] == "silme dogrula"
    assert captured["params"]["project"] == "pk"
    assert captured["timeout"] == ups.PROMPT_RECALL_HTTP_TIMEOUT_SECONDS


def test_fetch_prompt_recall_block_empty_on_non_200(monkeypatch):
    class FakeResp:
        status_code = 503

        def json(self):
            return {"block": "should-not-be-used"}

    monkeypatch.setattr(ups.httpx, "get", lambda url, params=None, timeout=None: FakeResp())
    assert ups.fetch_prompt_recall_block(prompt="x", project="pk") == ""
