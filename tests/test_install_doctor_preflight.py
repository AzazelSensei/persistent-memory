import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
PREFLIGHT_MARKER = "persistent_memory.doctor"
PREFLIGHT_PYTHONPATH = "PYTHONPATH"
PREFLIGHT_PYTHON = "python3"
DOCTOR_SCAN_HEADER = "prerequisite scan"


def _run_dry(env_overrides):
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )


def test_dry_run_mentions_doctor_preflight():
    out = _run_dry({"PM_TARGET_HOME": "/tmp/pm-doctor-home"}).stdout
    assert PREFLIGHT_MARKER in out


def test_doctor_runs_before_skill_and_hooks():
    out = _run_dry({"PM_TARGET_HOME": "/tmp/pm-doctor-home"}).stdout
    doctor_idx = out.find(PREFLIGHT_MARKER)
    skill_idx = out.find("skills/persistent-memory")
    hooks_idx = out.find("settings.json")
    assert doctor_idx != -1
    assert skill_idx != -1
    assert hooks_idx != -1
    assert doctor_idx < skill_idx
    assert doctor_idx < hooks_idx


def test_dry_run_passes_dry_run_to_doctor():
    out = _run_dry({"PM_TARGET_HOME": "/tmp/pm-doctor-home"}).stdout
    preflight_line = next(line for line in out.splitlines() if PREFLIGHT_MARKER in line)
    assert "--dry-run" in preflight_line


def test_dry_run_actually_executes_doctor():
    out = _run_dry({"PM_TARGET_HOME": "/tmp/pm-doctor-home"}).stdout
    assert DOCTOR_SCAN_HEADER in out


def test_preflight_uses_pythonpath_and_bare_python3():
    source = INSTALL_SH.read_text()
    assert f'DOCTOR_MODULE="{PREFLIGHT_MARKER}"' in source
    run_doctor = source.split("run_doctor()", 1)[1].split("create_venv()", 1)[0]
    assert PREFLIGHT_PYTHONPATH in run_doctor
    assert PREFLIGHT_PYTHON in run_doctor
    assert "$DOCTOR_MODULE" in run_doctor
    assert "python3.12 -m" not in run_doctor
