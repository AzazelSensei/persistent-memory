import plistlib
from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parent.parent / "install.sh"
REPO_ROOT = INSTALL_SH.parent


def test_launchd_uses_module_entrypoint_not_uvicorn_app():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "persistent_memory.daemon" in text
    assert "persistent_memory.daemon.app:app" not in text
    assert "uvicorn" not in text


def test_launchd_configures_logs_via_python_module():
    from persistent_memory.daemon.launch_agent import build_launch_agent_plist
    raw = build_launch_agent_plist(
        python_bin="/venv/bin/python",
        working_dir=str(REPO_ROOT),
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    assert "StandardErrorPath" in parsed
    assert "StandardOutPath" in parsed
