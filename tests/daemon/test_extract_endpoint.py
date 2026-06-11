import json

import pytest

import persistent_memory.daemon.services as services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token
from starlette.testclient import TestClient


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _token(tmp_path):
    return load_or_create_token(tmp_path)


@pytest.fixture(autouse=True)
def _cwd_roots_env(monkeypatch, tmp_path):
    monkeypatch.setenv(services.CWD_ROOTS_ENV, str(tmp_path))


def _body(tmp_path):
    cwd = tmp_path / "proj"
    cwd.mkdir(exist_ok=True)
    return {"project": "abc123def456", "cwd": str(cwd)}


class _FakeProc:
    def __init__(self, returncode=None):
        self._returncode = returncode

    def poll(self):
        return self._returncode


def test_extract_requires_token(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/extract", json=_body(tmp_path))
    assert resp.status_code == 403


def test_extract_rejects_wrong_token(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/extract", json=_body(tmp_path), headers={"X-PM-Token": "deadbeef"})
    assert resp.status_code == 403


def test_extract_spawns_detached_claude_with_token(tmp_path, monkeypatch):
    services.reset_extraction_state()
    captured = {}

    def fake_popen(argv, *args, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeProc(returncode=None)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    client = _client(tmp_path)
    body = _body(tmp_path)
    resp = client.post("/api/extract", json=body, headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code in (200, 202)
    argv = captured["argv"]
    assert "claude" in argv
    assert "-p" in argv
    assert "--permission-mode" in argv
    assert "bypassPermissions" in argv
    assert body["cwd"] in argv
    assert captured["kwargs"].get("cwd") == body["cwd"]


def test_extract_does_not_block_on_claude(tmp_path, monkeypatch):
    services.reset_extraction_state()
    waited = {"value": False}

    class _BlockingProc:
        def wait(self, *args, **kwargs):
            waited["value"] = True

        def poll(self):
            return None

    monkeypatch.setattr(services.subprocess, "Popen", lambda *a, **k: _BlockingProc())
    client = _client(tmp_path)
    client.post("/api/extract", json=_body(tmp_path), headers={"X-PM-Token": _token(tmp_path)})
    assert waited["value"] is False


def test_extract_skips_second_when_already_running(tmp_path, monkeypatch):
    services.reset_extraction_state()
    spawns = {"count": 0}

    def fake_popen(argv, *args, **kwargs):
        spawns["count"] += 1
        return _FakeProc(returncode=None)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    client = _client(tmp_path)
    headers = {"X-PM-Token": _token(tmp_path)}
    first = client.post("/api/extract", json=_body(tmp_path), headers=headers)
    second = client.post("/api/extract", json=_body(tmp_path), headers=headers)
    assert first.status_code in (200, 202)
    assert second.status_code in (200, 202)
    assert spawns["count"] == 1
    assert second.json().get("status") == "already-running"


def test_extract_respawns_after_previous_finished(tmp_path, monkeypatch):
    services.reset_extraction_state()
    spawns = {"count": 0}

    def fake_popen(argv, *args, **kwargs):
        spawns["count"] += 1
        return _FakeProc(returncode=0)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    client = _client(tmp_path)
    headers = {"X-PM-Token": _token(tmp_path)}
    client.post("/api/extract", json=_body(tmp_path), headers=headers)
    client.post("/api/extract", json=_body(tmp_path), headers=headers)
    assert spawns["count"] == 2


def test_extract_is_post_only(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/extract").status_code == 405


def test_extract_kills_stale_process_and_respawns(tmp_path, monkeypatch):
    services.reset_extraction_state()
    spawns = {"count": 0}
    killed = {"value": False}

    class _HungProc:
        def poll(self):
            return None

        def kill(self):
            killed["value"] = True

    def fake_popen(argv, *args, **kwargs):
        spawns["count"] += 1
        return _HungProc()

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    client = _client(tmp_path)
    headers = {"X-PM-Token": _token(tmp_path)}
    client.post("/api/extract", json=_body(tmp_path), headers=headers)
    assert spawns["count"] == 1
    real_monotonic = services.time.monotonic
    monkeypatch.setattr(
        services.time,
        "monotonic",
        lambda: real_monotonic() + services.EXTRACTION_MAX_SECONDS + 1,
    )
    resp = client.post("/api/extract", json=_body(tmp_path), headers=headers)
    assert killed["value"] is True
    assert spawns["count"] == 2
    assert resp.json().get("status") == "started"


def _write_transcript(path, count):
    lines = [
        json.dumps(
            {
                "type": "user",
                "cwd": "/tmp/proj",
                "timestamp": f"2026-06-01T12:00:{i:02d}.000Z",
                "message": {"role": "user", "content": f"mesaj {i}"},
            }
        )
        for i in range(count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_prepare_extraction_input_resets_watermark_above_total(tmp_path, monkeypatch):
    monkeypatch.setenv(services.TRANSCRIPT_ROOTS_ENV, str(tmp_path))
    transcript = tmp_path / "sess-1.jsonl"
    _write_transcript(transcript, 50)
    wm_path = services._watermark_path(tmp_path, "sess-1")
    services._write_watermark(wm_path, 100)
    info = services.prepare_extraction_input(
        transcript_path=str(transcript), records_dir=tmp_path
    )
    assert info["new_count"] == 50
    assert info["is_baseline"] is False


def test_prepare_extraction_input_rejects_path_outside_allowed_roots(tmp_path, monkeypatch):
    monkeypatch.setenv(services.TRANSCRIPT_ROOTS_ENV, str(tmp_path / "allowed"))
    transcript = tmp_path / "outside" / "sess-2.jsonl"
    _write_transcript(transcript, 3)
    with pytest.raises(ValueError):
        services.prepare_extraction_input(
            transcript_path=str(transcript), records_dir=tmp_path
        )


def test_rejected_path_raises_transcript_path_error(tmp_path, monkeypatch):
    monkeypatch.setenv(services.TRANSCRIPT_ROOTS_ENV, str(tmp_path / "allowed"))
    transcript = tmp_path / "outside" / "sess-2.jsonl"
    _write_transcript(transcript, 3)
    with pytest.raises(services.TranscriptPathError):
        services.prepare_extraction_input(
            transcript_path=str(transcript), records_dir=tmp_path
        )


def test_prepare_extraction_input_accepts_path_under_allowed_root(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    monkeypatch.setenv(services.TRANSCRIPT_ROOTS_ENV, str(allowed))
    transcript = allowed / "sess-3.jsonl"
    _write_transcript(transcript, 3)
    info = services.prepare_extraction_input(
        transcript_path=str(transcript), records_dir=tmp_path
    )
    assert info["new_count"] == 3


def test_extract_endpoint_survives_disallowed_transcript_path(tmp_path, monkeypatch):
    services.reset_extraction_state()
    monkeypatch.setenv(services.TRANSCRIPT_ROOTS_ENV, str(tmp_path / "allowed"))
    monkeypatch.setattr(services.subprocess, "Popen", lambda *a, **k: _FakeProc(returncode=None))
    client = _client(tmp_path)
    body = {**_body(tmp_path), "transcript_path": str(tmp_path / "outside" / "x.jsonl")}
    resp = client.post("/api/extract", json=body, headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code in (200, 202)


def test_extract_disallowed_transcript_path_not_in_prompt(tmp_path, monkeypatch):
    services.reset_extraction_state()
    monkeypatch.setenv(services.TRANSCRIPT_ROOTS_ENV, str(tmp_path / "allowed"))
    captured = {}

    def fake_popen(argv, *args, **kwargs):
        captured["argv"] = argv
        return _FakeProc(returncode=None)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    client = _client(tmp_path)
    outside = str(tmp_path / "outside" / "x.jsonl")
    body = {**_body(tmp_path), "transcript_path": outside}
    resp = client.post("/api/extract", json=body, headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code in (200, 202)
    assert all(outside not in arg for arg in captured["argv"])


def test_extract_allowed_path_slice_error_falls_back_to_raw_path(tmp_path, monkeypatch):
    services.reset_extraction_state()
    allowed = tmp_path / "allowed"
    monkeypatch.setenv(services.TRANSCRIPT_ROOTS_ENV, str(allowed))
    transcript = allowed / "sess-4.jsonl"
    _write_transcript(transcript, 3)
    captured = {}

    def fake_popen(argv, *args, **kwargs):
        captured["argv"] = argv
        return _FakeProc(returncode=None)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)

    def broken_prepare(**kwargs):
        raise OSError("slice yazilamadi")

    monkeypatch.setattr(services, "prepare_extraction_input", broken_prepare)
    client = _client(tmp_path)
    body = {**_body(tmp_path), "transcript_path": str(transcript)}
    resp = client.post("/api/extract", json=body, headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code in (200, 202)
    assert any(str(transcript) in arg for arg in captured["argv"])


def test_extract_closes_log_handle_in_parent(tmp_path, monkeypatch):
    services.reset_extraction_state()
    captured = {}

    def fake_popen(argv, *args, **kwargs):
        captured["stdout"] = kwargs.get("stdout")
        return _FakeProc(returncode=None)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    client = _client(tmp_path)
    client.post("/api/extract", json=_body(tmp_path), headers={"X-PM-Token": _token(tmp_path)})
    assert captured["stdout"] is not None
    assert captured["stdout"].closed is True


def _capture_popen(monkeypatch):
    captured = {}

    def fake_popen(argv, *args, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeProc(returncode=None)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    return captured


def test_extract_rejects_cwd_outside_allowed_roots(tmp_path, monkeypatch):
    services.reset_extraction_state()
    captured = _capture_popen(monkeypatch)
    client = _client(tmp_path)
    body = {"project": "abc123def456", "cwd": "/etc"}
    resp = client.post("/api/extract", json=body, headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code in (200, 202)
    assert resp.json().get("status") == "started"
    assert all("/etc" not in arg for arg in captured["argv"])
    assert captured["kwargs"].get("cwd") is None


def test_extract_rejects_cwd_that_is_not_a_directory(tmp_path, monkeypatch):
    services.reset_extraction_state()
    captured = _capture_popen(monkeypatch)
    client = _client(tmp_path)
    missing = str(tmp_path / "yok-boyle-dizin")
    body = {"project": "abc123def456", "cwd": missing}
    resp = client.post("/api/extract", json=body, headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code in (200, 202)
    assert resp.json().get("status") == "started"
    assert all(missing not in arg for arg in captured["argv"])
    assert captured["kwargs"].get("cwd") is None


def test_extract_allowed_cwd_passes_add_dir_and_popen_cwd(tmp_path, monkeypatch):
    services.reset_extraction_state()
    captured = _capture_popen(monkeypatch)
    client = _client(tmp_path)
    body = _body(tmp_path)
    resp = client.post("/api/extract", json=body, headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code in (200, 202)
    argv = captured["argv"]
    assert "--add-dir" in argv
    assert body["cwd"] in argv
    assert captured["kwargs"].get("cwd") == body["cwd"]


def test_validate_cwd_rejects_system_path_with_default_roots(monkeypatch):
    monkeypatch.delenv(services.CWD_ROOTS_ENV, raising=False)
    with pytest.raises(services.CwdValidationError):
        services._validate_cwd("/etc")


def test_validate_cwd_accepts_home_with_default_roots(monkeypatch):
    monkeypatch.delenv(services.CWD_ROOTS_ENV, raising=False)
    from pathlib import Path

    resolved = services._validate_cwd(str(Path.home()))
    assert resolved == Path.home().resolve()


def test_validate_cwd_error_is_value_error_but_not_transcript_error():
    assert issubclass(services.CwdValidationError, ValueError)
    assert not issubclass(services.CwdValidationError, services.TranscriptPathError)
