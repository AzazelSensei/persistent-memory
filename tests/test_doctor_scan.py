import urllib.error

import pytest

from persistent_memory import doctor


PREREQ_NAMES = {
    "homebrew",
    "jq",
    "python3.12",
    "venv",
    "ollama",
    "ollama-server",
    "bge-m3",
    "graphify",
    "claude",
    "claude-mem",
    "git",
}


class _OkResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _all_present_env(monkeypatch, tmp_path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("")

    def fake_which(name):
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr(doctor.shutil, "which", fake_which)
    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_ollama_has_model", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_can_import_in_venv", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_can_import_python312", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_claude_mem_present", lambda: True)
    monkeypatch.setattr(doctor, "_python312_path", lambda: "/opt/homebrew/bin/python3.12")
    return tmp_path


def test_check_result_model_fields():
    result = doctor.CheckResult(
        name="jq",
        present=False,
        detail="bulunamadi",
        category="system",
        fix_commands=[["brew", "install", "jq"]],
        critical=False,
    )
    assert result.name == "jq"
    assert result.present is False
    assert result.category == "system"
    assert result.fix_commands == [["brew", "install", "jq"]]
    assert result.critical is False


def test_scan_returns_all_prereqs(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)
    results = doctor.scan(records_dir=tmp_path)
    assert {r.name for r in results} == PREREQ_NAMES


def test_scan_all_present(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)
    results = doctor.scan(records_dir=tmp_path)
    assert all(r.present for r in results), [r.name for r in results if not r.present]


def test_scan_detects_missing_jq(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "jq":
            return None
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr(doctor.shutil, "which", fake_which)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["jq"].present is False
    assert results["jq"].category == "system"
    assert results["jq"].fix_commands == [["brew", "install", "jq"]]


def test_scan_detects_missing_brew_is_manual(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "brew":
            return None
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr(doctor.shutil, "which", fake_which)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["homebrew"].present is False
    assert results["homebrew"].category == "manual"
    assert results["homebrew"].fix_commands == []


def test_scan_detects_ollama_server_down_is_critical(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda: False)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["ollama-server"].present is False
    assert results["ollama-server"].critical is True
    assert results["ollama-server"].fix_commands == [["brew", "services", "start", "ollama"]]


def test_scan_detects_missing_bge_m3_is_critical(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor, "_ollama_has_model", lambda *a, **k: False)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["bge-m3"].present is False
    assert results["bge-m3"].critical is True
    assert results["bge-m3"].fix_commands == [["ollama", "pull", "bge-m3"]]


def test_scan_detects_missing_venv_is_critical(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor, "_can_import_in_venv", lambda *a, **k: False)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["venv"].present is False
    assert results["venv"].critical is True
    assert results["venv"].category == "local"


def test_scan_detects_missing_graphify(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor, "_can_import_python312", lambda module: False)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["graphify"].present is False
    assert results["graphify"].category == "local"
    assert results["graphify"].fix_commands == [
        ["python3.12", "-m", "pip", "install", "--user", "graphifyy"]
    ]


def test_scan_python312_fix_command(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor, "_python312_path", lambda: None)

    def fake_which(name):
        if name == "python3.12":
            return None
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr(doctor.shutil, "which", fake_which)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["python3.12"].present is False
    assert results["python3.12"].category == "system"
    assert results["python3.12"].fix_commands == [["brew", "install", "python@3.12"]]


def test_scan_claude_missing_is_manual(monkeypatch, tmp_path):
    _all_present_env(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "claude":
            return None
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr(doctor.shutil, "which", fake_which)
    results = {r.name: r for r in doctor.scan(records_dir=tmp_path)}
    assert results["claude"].present is False
    assert results["claude"].category == "manual"


def test_probe_ollama_server_uses_short_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _OkResp()

    monkeypatch.setattr(doctor.urllib.request, "urlopen", fake_urlopen)
    assert doctor._probe_ollama_server() is True
    assert captured["url"] == "http://localhost:11434/api/tags"
    assert captured["timeout"] <= 3.0


def test_probe_ollama_server_false_on_url_error(monkeypatch):
    def boom(url, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", boom)
    assert doctor._probe_ollama_server() is False


def test_probe_ollama_server_false_on_timeout(monkeypatch):
    def boom(url, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", boom)
    assert doctor._probe_ollama_server() is False
