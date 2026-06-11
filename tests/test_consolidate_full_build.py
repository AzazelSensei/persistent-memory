import subprocess
from pathlib import Path
import pytest
from persistent_memory.consolidate import run_full_build


def test_invokes_claude_headless(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result":"done"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_full_build(Path("/tmp/corpus"))
    assert result.returncode == 0
    assert captured["cmd"][0] == "claude"
    assert "-p" in captured["cmd"]
    prompt_idx = captured["cmd"].index("-p") + 1
    assert captured["cmd"][prompt_idx] == "/graphify /tmp/corpus --update"


def test_full_build_uses_bypass_permissions(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_full_build(Path("/tmp/corpus"))
    assert "--permission-mode" in captured["cmd"]
    mode_idx = captured["cmd"].index("--permission-mode") + 1
    assert captured["cmd"][mode_idx] == "bypassPermissions"
    assert "--output-format" in captured["cmd"]


def test_full_build_nonzero_raises(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="auth error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="full build failed"):
        run_full_build(Path("/tmp/corpus"))
