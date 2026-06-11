from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parent.parent / "install.sh"


def test_launchd_uses_module_entrypoint_not_uvicorn_app():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "persistent_memory.daemon" in text
    assert "persistent_memory.daemon.app:app" not in text
    assert "uvicorn" not in text


def test_launchd_configures_logs():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "StandardErrorPath" in text
    assert "StandardOutPath" in text
