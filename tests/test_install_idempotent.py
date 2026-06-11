import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
HOOK_COMMAND_PREFIX = "persistent_memory.hooks."
HOOK_EVENTS = ("UserPromptSubmit", "Stop", "PreCompact", "SessionStart")
LAUNCHD_LABEL = "com.persistent-memory.daemon"


def _function_body(name: str) -> str:
    source = INSTALL_SH.read_text()
    after = source.split(f"{name}()", 1)[1]
    return after.split("\n}", 1)[0]


def test_create_venv_uses_python312():
    body = _function_body("create_venv")
    assert "python3.12 -m venv" in body


def test_install_launchd_clears_stale_label_before_load():
    body = _function_body("install_launchd")
    assert "launchctl bootout" in body
    assert LAUNCHD_LABEL in body
    assert f"launchctl remove {LAUNCHD_LABEL}" in body
    bootout_idx = body.find("launchctl bootout")
    load_idx = body.find('launchctl load "$PLIST_DEST"')
    assert bootout_idx != -1
    assert load_idx != -1
    assert bootout_idx < load_idx

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not available")


def _run_install(fake_home: Path):
    env = os.environ.copy()
    env.update(
        {
            "PM_TARGET_HOME": str(fake_home),
            "PM_SKIP_VENV": "1",
            "PM_SKIP_LAUNCHD": "1",
            "PM_SKIP_DOCTOR": "1",
        }
    )
    return subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        env=env,
    )


def _settings(fake_home: Path) -> dict:
    return json.loads((fake_home / ".claude" / "settings.json").read_text())


def _count_pm_entries(event_entries) -> int:
    count = 0
    for entry in event_entries:
        for hook in entry.get("hooks", []):
            if HOOK_COMMAND_PREFIX in hook.get("command", ""):
                count += 1
    return count


def test_register_hooks_is_idempotent_and_preserves_user_hooks(tmp_path):
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    seeded = {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "echo user-hook"}]}
            ]
        }
    }
    (claude_dir / "settings.json").write_text(json.dumps(seeded))

    first = _run_install(fake_home)
    assert first.returncode == 0, first.stderr
    second = _run_install(fake_home)
    assert second.returncode == 0, second.stderr

    settings = _settings(fake_home)
    for event in HOOK_EVENTS:
        assert _count_pm_entries(settings["hooks"][event]) == 1, event

    ups = settings["hooks"]["UserPromptSubmit"]
    commands = [h["command"] for e in ups for h in e["hooks"]]
    assert "echo user-hook" in commands
