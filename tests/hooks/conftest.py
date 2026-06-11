import pytest

from persistent_memory.hooks import session_start as ss


@pytest.fixture(autouse=True)
def _no_real_doctor_probe(monkeypatch):
    monkeypatch.setattr(ss, "detect_missing_critical", lambda *a, **k: [], raising=False)
