"""Tests for Kimi Code CLI extraction backend routing and argv builder."""

from pathlib import Path

import pytest

import persistent_memory.daemon.services as services
import persistent_memory.extraction_prompt as ep
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token
from starlette.testclient import TestClient


class _FakeProc:
    def __init__(self, returncode=None):
        self._returncode = returncode

    def poll(self):
        return self._returncode


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _token(tmp_path):
    return load_or_create_token(tmp_path)


@pytest.fixture(autouse=True)
def _reset_extraction(monkeypatch, tmp_path):
    services.reset_extraction_state()
    monkeypatch.setenv(services.CWD_ROOTS_ENV, str(tmp_path))
    yield
    services.reset_extraction_state()


class TestExtractionBackendFor:
    def test_kimi_root_returns_kimi(self):
        path = Path.home() / ".kimi-code" / "sessions" / "sess" / "agents" / "main" / "wire.jsonl"
        assert services._extraction_backend_for(path) == "kimi"

    def test_kimi_root_nested_returns_kimi(self):
        path = Path.home() / ".kimi-code" / "sub" / "wire.jsonl"
        assert services._extraction_backend_for(path) == "kimi"

    def test_claude_projects_root_returns_claude(self):
        path = Path.home() / ".claude" / "projects" / "-proj" / "sess.jsonl"
        assert services._extraction_backend_for(path) == "claude"

    def test_unrelated_path_returns_claude(self):
        path = Path("/tmp/transcripts/wire.jsonl")
        assert services._extraction_backend_for(path) == "claude"

    def test_none_returns_claude(self):
        assert services._extraction_backend_for(None) == "claude"


class TestBuildKimiExtractionArgv:
    def test_starts_with_kimi_prompt(self):
        argv = ep.build_kimi_extraction_argv(prompt="EXTRACT", cwd="/tmp/p")
        assert argv[0] == "kimi"
        assert argv[1] == "-p"
        assert "EXTRACT" in argv

    def test_uses_yolo_and_text_output(self):
        argv = ep.build_kimi_extraction_argv(prompt="EXTRACT", cwd="/tmp/p")
        assert "-y" in argv
        assert "--output-format" in argv
        assert "text" in argv

    def test_no_model_flag_when_default_empty(self, monkeypatch):
        monkeypatch.delenv("PM_KIMI_EXTRACTION_MODEL", raising=False)
        monkeypatch.setattr(ep, "KIMI_EXTRACTION_MODEL", "")
        argv = ep.build_kimi_extraction_argv(prompt="P", cwd="")
        assert "-m" not in argv

    def test_model_flag_when_constant_set(self, monkeypatch):
        monkeypatch.setattr(ep, "KIMI_EXTRACTION_MODEL", "kimi-k2")
        monkeypatch.delenv("PM_KIMI_EXTRACTION_MODEL", raising=False)
        argv = ep.build_kimi_extraction_argv(prompt="P", cwd="")
        assert "-m" in argv
        idx = argv.index("-m")
        assert argv[idx + 1] == "kimi-k2"

    def test_env_override_wins_over_constant(self, monkeypatch):
        monkeypatch.setattr(ep, "KIMI_EXTRACTION_MODEL", "from-constant")
        monkeypatch.setenv("PM_KIMI_EXTRACTION_MODEL", "from-env")
        argv = ep.build_kimi_extraction_argv(prompt="P", cwd="")
        assert "-m" in argv
        idx = argv.index("-m")
        assert argv[idx + 1] == "from-env"


class TestExtractEndpointKimiRouting:
    def test_kimi_transcript_spawns_kimi_binary(self, tmp_path, monkeypatch):
        services.reset_extraction_state()
        monkeypatch.delenv(services.TRANSCRIPT_ROOTS_ENV, raising=False)
        monkeypatch.setattr(services, "_resolve_kimi_bin", lambda env: "/usr/local/bin/kimi")
        captured = {}

        def fake_popen(argv, *args, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return _FakeProc(returncode=None)

        monkeypatch.setattr(services.subprocess, "Popen", fake_popen)

        def fake_prepare(**kwargs):
            slice_path = tmp_path / "slice.txt"
            slice_path.write_text("msg", encoding="utf-8")
            wm_path = services._watermark_path(tmp_path, "fake-sess")
            return {
                "session_id": "fake-sess",
                "total": 3,
                "new_count": 3,
                "is_baseline": False,
                "slice_path": str(slice_path),
                "wm_path": str(wm_path),
            }

        monkeypatch.setattr(services, "prepare_extraction_input", fake_prepare)

        cwd = tmp_path / "proj"
        cwd.mkdir()
        kimi_transcript = str(Path.home() / ".kimi-code" / "sessions" / "fake-sess" / "agents" / "main" / "wire.jsonl")
        result = services.trigger_extraction(
            project="my-kimi-proj",
            cwd=str(cwd),
            transcript_path=kimi_transcript,
            records_dir=tmp_path,
        )
        assert result["status"] == services.EXTRACTION_STARTED_STATUS
        assert captured["argv"][0] == "kimi"
        assert captured["kwargs"].get("cwd") == str(cwd)

    def test_missing_kimi_falls_back_to_claude(self, tmp_path, monkeypatch, caplog):
        import logging

        services.reset_extraction_state()
        monkeypatch.delenv(services.TRANSCRIPT_ROOTS_ENV, raising=False)
        real_which = services.shutil.which

        def fake_which(name, **kwargs):
            if name == "kimi":
                return None
            return real_which(name, **kwargs)

        monkeypatch.setattr(services.shutil, "which", fake_which)

        captured = {}

        def fake_popen(argv, *args, **kwargs):
            captured["argv"] = argv
            return _FakeProc(returncode=None)

        monkeypatch.setattr(services.subprocess, "Popen", fake_popen)

        def fake_prepare(**kwargs):
            slice_path = tmp_path / "slice.txt"
            slice_path.write_text("msg", encoding="utf-8")
            wm_path = services._watermark_path(tmp_path, "fake-sess")
            return {
                "session_id": "fake-sess",
                "total": 3,
                "new_count": 3,
                "is_baseline": False,
                "slice_path": str(slice_path),
                "wm_path": str(wm_path),
            }

        monkeypatch.setattr(services, "prepare_extraction_input", fake_prepare)

        kimi_transcript = str(Path.home() / ".kimi-code" / "sessions" / "fake-sess" / "agents" / "main" / "wire.jsonl")
        cwd = tmp_path / "proj"
        cwd.mkdir()
        with caplog.at_level(logging.WARNING, logger="persistent_memory.daemon.services"):
            result = services.trigger_extraction(
                project="kimi-proj",
                cwd=str(cwd),
                transcript_path=kimi_transcript,
                records_dir=tmp_path,
            )
        assert result["status"] == services.EXTRACTION_STARTED_STATUS
        assert captured["argv"][0] == "claude"
        assert any("kimi" in rec.message.lower() for rec in caplog.records)
