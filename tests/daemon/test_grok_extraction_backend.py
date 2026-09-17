"""Tests for Grok CLI extraction backend routing and argv builder."""

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


@pytest.fixture(autouse=True)
def _reset_extraction(monkeypatch, tmp_path):
    services.reset_extraction_state()
    monkeypatch.setenv(services.CWD_ROOTS_ENV, str(tmp_path))
    yield
    services.reset_extraction_state()


class TestExtractionBackendForGrok:
    def test_grok_root_returns_grok(self):
        path = Path.home() / ".grok" / "sessions" / "enc" / "sess" / "chat_history.jsonl"
        assert services._extraction_backend_for(path) == "grok"

    def test_claude_still_claude(self):
        path = Path.home() / ".claude" / "projects" / "-proj" / "sess.jsonl"
        assert services._extraction_backend_for(path) == "claude"


class TestBuildGrokExtractionArgv:
    def test_starts_with_grok_prompt(self):
        argv = ep.build_grok_extraction_argv(prompt="EXTRACT", cwd="/tmp/repo")
        assert argv[0] == "grok"
        assert argv[1] == "-p"
        assert "EXTRACT" in argv

    def test_uses_always_approve_and_plain_output(self):
        argv = ep.build_grok_extraction_argv(prompt="EXTRACT", cwd="/tmp/repo")
        assert "--always-approve" in argv
        assert "--output-format" in argv
        assert "plain" in argv
        assert "--cwd" in argv
        assert "/tmp/repo" in argv
        assert "--effort" in argv
        assert "low" in argv
        assert "--no-subagents" in argv

    def test_model_env_override(self, monkeypatch):
        monkeypatch.setenv("PM_GROK_EXTRACTION_MODEL", "grok-4")
        argv = ep.build_grok_extraction_argv(prompt="P", cwd="")
        assert "-m" in argv
        assert argv[argv.index("-m") + 1] == "grok-4"


class TestExtractEndpointGrokRouting:
    def test_grok_transcript_spawns_grok_binary(self, tmp_path, monkeypatch):
        services.reset_extraction_state()
        monkeypatch.delenv(services.TRANSCRIPT_ROOTS_ENV, raising=False)
        monkeypatch.setattr(services, "_resolve_grok_bin", lambda env: "/usr/local/bin/grok")
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
        grok_transcript = str(
            Path.home() / ".grok" / "sessions" / "enc" / "sess" / "chat_history.jsonl"
        )
        result = services.trigger_extraction(
            project="my-grok-proj",
            cwd=str(cwd),
            transcript_path=grok_transcript,
            records_dir=tmp_path,
        )
        assert result["status"] == services.EXTRACTION_STARTED_STATUS
        assert result["backend"] == "grok"
        assert captured["argv"][0] == "grok"
        assert "--always-approve" in captured["argv"]
        assert captured["kwargs"].get("cwd") == str(tmp_path.parent)

    def test_missing_grok_does_not_cross_host_fallback(self, tmp_path, monkeypatch, caplog):
        import logging

        services.reset_extraction_state()
        monkeypatch.delenv(services.TRANSCRIPT_ROOTS_ENV, raising=False)
        monkeypatch.setattr(services, "_resolve_grok_bin", lambda env: None)

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

        grok_transcript = str(
            Path.home() / ".grok" / "sessions" / "enc" / "sess" / "chat_history.jsonl"
        )
        cwd = tmp_path / "proj"
        cwd.mkdir()
        with caplog.at_level(logging.WARNING, logger="persistent_memory.daemon.services"):
            result = services.trigger_extraction(
                project="grok-proj",
                cwd=str(cwd),
                transcript_path=grok_transcript,
                records_dir=tmp_path,
            )
        assert result["status"] == services.EXTRACTION_BACKEND_UNAVAILABLE_STATUS
        assert result["backend"] == "grok"
        assert "argv" not in captured
        assert any("grok" in rec.message.lower() for rec in caplog.records)
