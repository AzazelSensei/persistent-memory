import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _run_dry(env_overrides):
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
    )


def test_install_script_exists_and_executable():
    assert INSTALL_SH.exists()


def test_dry_run_exits_zero_and_writes_nothing(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    result = _run_dry({"PM_TARGET_HOME": str(fake_home)})
    assert result.returncode == 0, result.stderr
    assert not (fake_home / ".claude").exists()


def test_dry_run_reports_planned_actions(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    result = _run_dry({"PM_TARGET_HOME": str(fake_home)})
    out = result.stdout
    assert "DRY-RUN" in out
    assert "skills/persistent-memory" in out
    assert "settings.json" in out
    assert "LaunchAgents" in out
    assert ".venv" in out


def test_dry_run_launchd_reports_pm_lang(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    result = _run_dry({"PM_TARGET_HOME": str(fake_home), "PM_LANG": "tr"})
    assert result.returncode == 0, result.stderr
    assert "PM_LANG=tr" in result.stdout


def test_dry_run_launchd_reports_detected_lang_from_env(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    result = _run_dry({"PM_TARGET_HOME": str(fake_home), "PM_LANG": "", "LC_ALL": "en_US.UTF-8", "LANG": ""})
    assert result.returncode == 0, result.stderr
    assert "PM_LANG=en" in result.stdout


def test_dry_run_lists_all_five_hooks(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    out = _run_dry({"PM_TARGET_HOME": str(fake_home)}).stdout
    for hook in ("UserPromptSubmit", "Stop", "PreCompact", "SessionStart", "PreToolUse"):
        assert hook in out


def test_dry_run_plans_codex_skill_copy_when_codex_present(tmp_path):
    fake_home = tmp_path / "home"
    (fake_home / ".codex").mkdir(parents=True)
    result = _run_dry({"PM_TARGET_HOME": str(fake_home), "PM_INSTALL_CODEX": "1"})
    assert result.returncode == 0, result.stderr
    assert ".codex/skills/persistent-memory" in result.stdout
