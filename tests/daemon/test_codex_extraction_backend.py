"""Tests for per-source extraction backend routing and codex argv builder."""

import json
import os
from pathlib import Path

import pytest

import persistent_memory.daemon.services as services
import persistent_memory.extraction_prompt as ep
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _token(tmp_path):
    return load_or_create_token(tmp_path)


class _FakeProc:
    def __init__(self, returncode=None):
        self._returncode = returncode

    def poll(self):
        return self._returncode


def _write_transcript(path, count):
    lines = [
        json.dumps(
            {
                "type": "user",
                "cwd": "/tmp/proj",
                "timestamp": f"2026-06-01T12:00:{i:02d}.000Z",
                "message": {"role": "user", "content": f"msg {i}"},
            }
        )
        for i in range(count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_extraction(monkeypatch, tmp_path):
    services.reset_extraction_state()
    monkeypatch.setenv(services.CWD_ROOTS_ENV, str(tmp_path))
    yield
    services.reset_extraction_state()


# ---------------------------------------------------------------------------
# 1. _extraction_backend_for routing
# ---------------------------------------------------------------------------

class TestExtractionBackendFor:
    def test_codex_root_returns_codex(self):
        path = Path.home() / ".codex" / "sessions" / "sess-abc.jsonl"
        assert services._extraction_backend_for(path) == "codex"

    def test_codex_root_nested_returns_codex(self):
        path = Path.home() / ".codex" / "sub" / "dir" / "sess.jsonl"
        assert services._extraction_backend_for(path) == "codex"

    def test_claude_projects_root_returns_claude(self):
        path = Path.home() / ".claude" / "projects" / "-proj" / "sess.jsonl"
        assert services._extraction_backend_for(path) == "claude"

    def test_unrelated_path_returns_claude(self):
        path = Path("/tmp/transcripts/sess-x.jsonl")
        assert services._extraction_backend_for(path) == "claude"

    def test_none_returns_claude(self):
        assert services._extraction_backend_for(None) == "claude"

    def test_env_extra_root_returns_claude(self, tmp_path):
        # Extra roots added via PM_TRANSCRIPT_ROOTS are NOT codex roots;
        # routing is based purely on whether path is under ~/.codex.
        path = tmp_path / "extra" / "sess.jsonl"
        assert services._extraction_backend_for(path) == "claude"


# ---------------------------------------------------------------------------
# 2. build_codex_extraction_argv
# ---------------------------------------------------------------------------

class TestBuildCodexExtractionArgv:
    def test_starts_with_codex_exec(self, monkeypatch):
        monkeypatch.setenv("PM_CODEX_BIN", "codex")
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        assert argv[0] == "codex"
        assert argv[1] == "exec"

    def test_codex_bin_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("PM_CODEX_BIN", "/custom/codex")
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        assert argv[0] == "/custom/codex"

    def test_prefers_codex_app_binary_when_present(self, monkeypatch, tmp_path):
        app_bin = tmp_path / "Codex.app" / "Contents" / "Resources" / "codex"
        app_bin.parent.mkdir(parents=True)
        app_bin.write_text("", encoding="utf-8")
        monkeypatch.delenv("PM_CODEX_BIN", raising=False)
        monkeypatch.setattr(ep, "CODEX_APP_BIN", app_bin)
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        assert argv[0] == str(app_bin)

    def test_has_ephemeral_and_skip_git(self):
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        assert "--ephemeral" in argv
        assert "--skip-git-repo-check" in argv

    def test_ignores_user_config(self):
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        assert "--ignore-user-config" in argv

    def test_has_sandbox_workspace_write(self):
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        idx = argv.index("-s")
        assert argv[idx + 1] == "workspace-write"

    def test_sets_low_reasoning_effort(self, monkeypatch):
        monkeypatch.delenv("PM_CODEX_EXTRACTION_EFFORT", raising=False)
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        idx = argv.index("-c")
        assert argv[idx + 1] == 'model_reasoning_effort="low"'

    def test_effort_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("PM_CODEX_EXTRACTION_EFFORT", "medium")
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/tmp/rec"))
        idx = argv.index("-c")
        assert argv[idx + 1] == 'model_reasoning_effort="medium"'

    def test_has_cd_records_repo_root(self):
        argv = ep.build_codex_extraction_argv(prompt="HELLO", records_dir=Path("/home/user/repo/docs"))
        assert "-C" in argv
        idx = argv.index("-C")
        # records_repo_root is parent of records_dir
        assert argv[idx + 1] == "/home/user/repo"

    def test_prompt_passed_as_last_positional(self):
        argv = ep.build_codex_extraction_argv(prompt="EXTRACT THIS", records_dir=Path("/tmp/rec"))
        assert argv[-1] == "EXTRACT THIS"

    def test_default_model_is_codex_spark(self, monkeypatch):
        monkeypatch.delenv("PM_CODEX_EXTRACTION_MODEL", raising=False)
        argv = ep.build_codex_extraction_argv(prompt="P", records_dir=Path("/tmp/rec"))
        idx = argv.index("-m")
        assert argv[idx + 1] == "gpt-5.3-codex-spark"

    def test_no_model_flag_when_model_is_empty(self, monkeypatch):
        monkeypatch.delenv("PM_CODEX_EXTRACTION_MODEL", raising=False)
        monkeypatch.setattr(ep, "CODEX_EXTRACTION_MODEL", "")
        argv = ep.build_codex_extraction_argv(prompt="P", records_dir=Path("/tmp/rec"))
        assert "-m" not in argv
        assert "--model" not in argv

    def test_model_flag_when_constant_set(self, monkeypatch):
        monkeypatch.setattr(ep, "CODEX_EXTRACTION_MODEL", "some-model")
        monkeypatch.delenv("PM_CODEX_EXTRACTION_MODEL", raising=False)
        argv = ep.build_codex_extraction_argv(prompt="P", records_dir=Path("/tmp/rec"))
        assert "-m" in argv
        idx = argv.index("-m")
        assert argv[idx + 1] == "some-model"

    def test_env_override_wins_over_constant(self, monkeypatch):
        monkeypatch.setattr(ep, "CODEX_EXTRACTION_MODEL", "from-constant")
        monkeypatch.setenv("PM_CODEX_EXTRACTION_MODEL", "from-env")
        argv = ep.build_codex_extraction_argv(prompt="P", records_dir=Path("/tmp/rec"))
        assert "-m" in argv
        idx = argv.index("-m")
        assert argv[idx + 1] == "from-env"


# ---------------------------------------------------------------------------
# 3. Endpoint-level: codex transcript path → codex argv
# ---------------------------------------------------------------------------

class TestExtractEndpointCodexRouting:
    """Payload with a ~/.codex/... transcript should spawn codex, not claude."""

    def _codex_transcript(self, tmp_path):
        """
        Real path must pass _validate_transcript_path AND map to codex backend.
        We override PM_TRANSCRIPT_ROOTS to include ~/.codex so the validator
        accepts it.  The backend router always checks Path.home()/".codex"
        independently of PM_TRANSCRIPT_ROOTS.
        """
        codex_root = Path.home() / ".codex"
        transcript = codex_root / "sessions" / "fake-sess.jsonl"
        return transcript

    def test_codex_transcript_spawns_codex_binary(self, tmp_path, monkeypatch):
        services.reset_extraction_state()
        # Allow validator to accept ~/.codex path (it's in DEFAULT_TRANSCRIPT_ROOTS)
        monkeypatch.delenv(services.TRANSCRIPT_ROOTS_ENV, raising=False)
        monkeypatch.setattr(services, "_resolve_codex_bin", lambda env: "/usr/local/bin/codex")
        captured = {}

        def fake_popen(argv, *args, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return _FakeProc(returncode=None)

        monkeypatch.setattr(services.subprocess, "Popen", fake_popen)

        def fake_prepare(**kwargs):
            # Return a valid slice_info so extraction proceeds immediately.
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
        result = services.trigger_extraction(
            project="my-codex-proj",
            cwd=str(cwd),
            transcript_path=str(self._codex_transcript(tmp_path)),
            records_dir=tmp_path,
        )
        assert result["status"] == services.EXTRACTION_STARTED_STATUS
        assert "codex" in captured["argv"][0].lower() or captured["argv"][0] == "codex"
        # Must NOT start with claude
        assert captured["argv"][0] != "claude"

    def test_claude_transcript_spawns_claude_binary(self, tmp_path, monkeypatch):
        services.reset_extraction_state()
        monkeypatch.delenv(services.TRANSCRIPT_ROOTS_ENV, raising=False)
        captured = {}

        def fake_popen(argv, *args, **kwargs):
            captured["argv"] = argv
            return _FakeProc(returncode=None)

        monkeypatch.setattr(services.subprocess, "Popen", fake_popen)

        def fake_prepare(**kwargs):
            slice_path = tmp_path / "slice.txt"
            slice_path.write_text("msg", encoding="utf-8")
            wm_path = services._watermark_path(tmp_path, "claude-sess")
            return {
                "session_id": "claude-sess",
                "total": 3,
                "new_count": 3,
                "is_baseline": False,
                "slice_path": str(slice_path),
                "wm_path": str(wm_path),
            }

        monkeypatch.setattr(services, "prepare_extraction_input", fake_prepare)

        cwd = tmp_path / "proj"
        cwd.mkdir()
        claude_transcript = Path.home() / ".claude" / "projects" / "-proj" / "claude-sess.jsonl"
        result = services.trigger_extraction(
            project="my-claude-proj",
            cwd=str(cwd),
            transcript_path=str(claude_transcript),
            records_dir=tmp_path,
        )
        assert result["status"] == services.EXTRACTION_STARTED_STATUS
        assert captured["argv"][0] == "claude"

    def test_no_transcript_spawns_claude_binary(self, tmp_path, monkeypatch):
        services.reset_extraction_state()
        captured = {}

        def fake_popen(argv, *args, **kwargs):
            captured["argv"] = argv
            return _FakeProc(returncode=None)

        monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
        cwd = tmp_path / "proj"
        cwd.mkdir()
        result = services.trigger_extraction(
            project="no-transcript-proj",
            cwd=str(cwd),
            transcript_path=None,
            records_dir=tmp_path,
        )
        assert result["status"] == services.EXTRACTION_STARTED_STATUS
        assert captured["argv"][0] == "claude"


# ---------------------------------------------------------------------------
# 4. Codex binary missing → fallback to claude + warning
# ---------------------------------------------------------------------------

class TestCodexBinaryMissingFallback:
    def test_missing_codex_falls_back_to_claude(self, tmp_path, monkeypatch, caplog):
        import logging

        services.reset_extraction_state()
        monkeypatch.delenv(services.TRANSCRIPT_ROOTS_ENV, raising=False)
        monkeypatch.delenv("PM_CODEX_BIN", raising=False)
        monkeypatch.setattr(ep, "CODEX_APP_BIN", tmp_path / "missing-codex-app-bin")
        # Make shutil.which return None for "codex"
        real_which = services.shutil.which

        def fake_which(name, **kwargs):
            if name == "codex":
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

        codex_transcript = str(Path.home() / ".codex" / "sessions" / "fake-sess.jsonl")
        cwd = tmp_path / "proj"
        cwd.mkdir()
        with caplog.at_level(logging.WARNING, logger="persistent_memory.daemon.services"):
            result = services.trigger_extraction(
                project="codex-proj",
                cwd=str(cwd),
                transcript_path=codex_transcript,
                records_dir=tmp_path,
            )
        assert result["status"] == services.EXTRACTION_STARTED_STATUS
        # Falls back to claude
        assert captured["argv"][0] == "claude"
        # Warning must be logged
        assert any("codex" in rec.message.lower() for rec in caplog.records)
