import pytest

from persistent_memory import doctor
from persistent_memory.doctor import CheckResult


def _result(name="jq", present=False):
    return CheckResult(
        name=name,
        present=present,
        detail="x",
        category="system",
        fix_commands=[["brew", "install", name]],
        critical=False,
    )


def test_main_default_runs_full_auto_fix(monkeypatch):
    monkeypatch.setattr(doctor, "scan", lambda records_dir=None: [_result()])
    captured = {}

    def fake_fix(results, *, dry_run=False):
        captured["dry_run"] = dry_run
        captured["results"] = results
        return [{"name": "jq", "action": "fixed", "commands": []}]

    monkeypatch.setattr(doctor, "fix_all", fake_fix)
    assert doctor.main([]) == 0
    assert captured["dry_run"] is False
    assert len(captured["results"]) == 1


def test_main_check_does_not_fix(monkeypatch):
    monkeypatch.setattr(doctor, "scan", lambda records_dir=None: [_result()])
    called = []
    monkeypatch.setattr(doctor, "fix_all", lambda *a, **k: called.append(1) or [])
    assert doctor.main(["--check"]) == 0
    assert called == []


def test_main_dry_run_passes_dry_run_true(monkeypatch):
    monkeypatch.setattr(doctor, "scan", lambda records_dir=None: [_result()])
    captured = {}

    def fake_fix(results, *, dry_run=False):
        captured["dry_run"] = dry_run
        return []

    monkeypatch.setattr(doctor, "fix_all", fake_fix)
    assert doctor.main(["--dry-run"]) == 0
    assert captured["dry_run"] is True


def test_main_prints_report(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "scan", lambda records_dir=None: [_result(present=True)])
    monkeypatch.setattr(doctor, "fix_all", lambda *a, **k: [{"name": "jq", "action": "skipped", "commands": []}])
    doctor.main([])
    out = capsys.readouterr().out
    assert "jq" in out
