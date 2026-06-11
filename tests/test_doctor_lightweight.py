import pytest

from persistent_memory import doctor


def test_lightweight_detect_returns_missing_critical(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda *a, **k: False)
    monkeypatch.setattr(doctor, "_ollama_has_model", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_can_import_in_venv", lambda *a, **k: True)
    missing = doctor.detect_missing_critical(records_dir=tmp_path)
    assert "ollama-server" in missing
    assert "bge-m3" not in missing
    assert "venv" not in missing


def test_lightweight_detect_empty_when_all_present(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_ollama_has_model", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_can_import_in_venv", lambda *a, **k: True)
    assert doctor.detect_missing_critical(records_dir=tmp_path) == []


def test_lightweight_detect_all_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda *a, **k: False)
    monkeypatch.setattr(doctor, "_ollama_has_model", lambda *a, **k: False)
    monkeypatch.setattr(doctor, "_can_import_in_venv", lambda *a, **k: False)
    missing = doctor.detect_missing_critical(records_dir=tmp_path)
    assert set(missing) == {"ollama-server", "bge-m3", "venv"}


def test_lightweight_detect_uses_short_timeout(monkeypatch, tmp_path):
    captured: dict[str, float] = {}

    def probe(timeout=None):
        captured["probe"] = timeout
        return True

    def has_model(model, timeout=None):
        captured["model"] = timeout
        return True

    def can_import(venv_dir, module, timeout=None):
        captured["venv"] = timeout
        return True

    monkeypatch.setattr(doctor, "_probe_ollama_server", probe)
    monkeypatch.setattr(doctor, "_ollama_has_model", has_model)
    monkeypatch.setattr(doctor, "_can_import_in_venv", can_import)
    doctor.detect_missing_critical(records_dir=tmp_path)
    assert captured["probe"] == doctor.SESSION_START_PROBE_TIMEOUT_SECONDS
    assert captured["model"] == doctor.SESSION_START_PROBE_TIMEOUT_SECONDS
    assert captured["venv"] == doctor.SESSION_START_PROBE_TIMEOUT_SECONDS
    assert doctor.SESSION_START_PROBE_TIMEOUT_SECONDS < doctor.OLLAMA_LIST_TIMEOUT_SECONDS


def test_scan_uses_generous_timeout(monkeypatch, tmp_path):
    captured: dict[str, float] = {}

    def has_model(model, timeout=None):
        captured["model"] = timeout
        return True

    def can_import(venv_dir, module, timeout=None):
        captured["venv"] = timeout
        return True

    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda *a, **k: True)
    monkeypatch.setattr(doctor, "_ollama_has_model", has_model)
    monkeypatch.setattr(doctor, "_can_import_in_venv", can_import)
    monkeypatch.setattr(doctor, "_can_import_python312", lambda *a, **k: True)
    doctor.scan(records_dir=tmp_path)
    assert captured["model"] == doctor.OLLAMA_LIST_TIMEOUT_SECONDS
    assert captured["venv"] == doctor.OLLAMA_LIST_TIMEOUT_SECONDS
