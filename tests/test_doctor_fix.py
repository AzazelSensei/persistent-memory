import subprocess

import pytest

from persistent_memory import doctor
from persistent_memory.doctor import CheckResult


class _RunRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def _missing(name, category, fix_commands, critical=False):
    return CheckResult(
        name=name,
        present=False,
        detail="missing",
        category=category,
        fix_commands=fix_commands,
        critical=critical,
    )


def _present(name, category):
    return CheckResult(
        name=name, present=True, detail="ok", category=category, fix_commands=[], critical=False
    )


def _patch_run(monkeypatch):
    recorder = _RunRecorder()
    monkeypatch.setattr(doctor.subprocess, "run", recorder)
    return recorder


def test_fix_all_dry_run_runs_nothing(monkeypatch):
    recorder = _patch_run(monkeypatch)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/brew")
    results = [_missing("jq", "system", [["brew", "install", "jq"]])]
    report = doctor.fix_all(results, dry_run=True)
    assert recorder.calls == []
    assert report[0]["action"] == "planned"
    assert report[0]["commands"] == [["brew", "install", "jq"]]


def test_fix_all_present_is_idempotent(monkeypatch):
    recorder = _patch_run(monkeypatch)
    results = [_present("jq", "system"), _present("ollama", "system")]
    report = doctor.fix_all(results)
    assert recorder.calls == []
    assert all(item["action"] == "skipped" for item in report)


def test_fix_all_runs_missing_system_fix(monkeypatch):
    recorder = _patch_run(monkeypatch)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/brew")
    results = [_present("homebrew", "manual"), _missing("jq", "system", [["brew", "install", "jq"]])]
    report = doctor.fix_all(results)
    assert ["brew", "install", "jq"] in recorder.calls
    jq_item = next(i for i in report if i["name"] == "jq")
    assert jq_item["action"] == "fixed"


def test_fix_all_skips_manual_items(monkeypatch):
    recorder = _patch_run(monkeypatch)
    results = [_missing("claude", "manual", [])]
    report = doctor.fix_all(results)
    assert recorder.calls == []
    claude_item = next(i for i in report if i["name"] == "claude")
    assert claude_item["action"] == "manual"


def test_fix_all_brew_missing_blocks_system_fixes(monkeypatch):
    recorder = _patch_run(monkeypatch)
    results = [
        _missing("homebrew", "manual", []),
        _missing("jq", "system", [["brew", "install", "jq"]]),
        _missing("ollama", "system", [["brew", "install", "ollama"]]),
    ]
    report = doctor.fix_all(results)
    assert recorder.calls == []
    jq_item = next(i for i in report if i["name"] == "jq")
    assert jq_item["action"] == "blocked"


def test_fix_all_brew_missing_still_runs_local_fixes(monkeypatch):
    recorder = _patch_run(monkeypatch)
    results = [
        _missing("homebrew", "manual", []),
        _missing("graphify", "local", [["python3.12", "-m", "pip", "install", "--user", "graphifyy"]]),
    ]
    report = doctor.fix_all(results)
    assert ["python3.12", "-m", "pip", "install", "--user", "graphifyy"] in recorder.calls


def test_fix_all_dependency_order(monkeypatch):
    recorder = _patch_run(monkeypatch)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/brew")
    monkeypatch.setattr(doctor, "_wait_for_ollama_server", lambda: True)
    results = [
        _missing("graphify", "local", [["python3.12", "-m", "pip", "install", "--user", "graphifyy"]]),
        _missing("bge-m3", "local", [["ollama", "pull", "bge-m3"]], critical=True),
        _missing("ollama-server", "system", [["brew", "services", "start", "ollama"]], critical=True),
        _missing("ollama", "system", [["brew", "install", "ollama"]]),
        _missing("venv", "local", [["python3.12", "-m", "venv", ".venv"]], critical=True),
        _missing("python3.12", "system", [["brew", "install", "python@3.12"]]),
        _missing("jq", "system", [["brew", "install", "jq"]]),
    ]
    doctor.fix_all(results)
    order = [c for c in recorder.calls]

    def idx(first_token, *rest):
        for i, call in enumerate(order):
            if call[: 1 + len(rest)] == [first_token, *rest]:
                return i
        raise AssertionError(f"command not run: {first_token} {rest}")

    assert idx("brew", "install", "jq") < idx("brew", "install", "python@3.12")
    assert idx("brew", "install", "python@3.12") < idx("python3.12", "-m", "venv")
    assert idx("python3.12", "-m", "venv") < idx("brew", "install", "ollama")
    assert idx("brew", "install", "ollama") < idx("brew", "services", "start", "ollama")
    assert idx("brew", "services", "start", "ollama") < idx("ollama", "pull", "bge-m3")
    assert idx("ollama", "pull", "bge-m3") < idx("python3.12", "-m", "pip")


def test_fix_all_polls_server_after_starting_service(monkeypatch):
    recorder = _patch_run(monkeypatch)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/brew")
    polled = []
    monkeypatch.setattr(doctor, "_wait_for_ollama_server", lambda: polled.append(1) or True)
    results = [
        _missing("ollama-server", "system", [["brew", "services", "start", "ollama"]], critical=True),
    ]
    doctor.fix_all(results)
    assert polled == [1]


def test_fix_all_records_command_failure(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/brew")

    def failing_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    monkeypatch.setattr(doctor.subprocess, "run", failing_run)
    results = [_missing("jq", "system", [["brew", "install", "jq"]])]
    report = doctor.fix_all(results)
    jq_item = next(i for i in report if i["name"] == "jq")
    assert jq_item["action"] == "failed"


class _FailingForRunRecorder:
    def __init__(self, fail_when):
        self.calls = []
        self._fail_when = fail_when

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        rc = 1 if self._fail_when(argv) else 0
        stderr = "boom" if rc else ""
        return subprocess.CompletedProcess(argv, rc, stdout="", stderr=stderr)


def test_fix_all_blocks_bge_m3_when_ollama_server_fails(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/brew")
    recorder = _FailingForRunRecorder(lambda argv: argv[:3] == ["brew", "services", "start"])
    monkeypatch.setattr(doctor.subprocess, "run", recorder)
    monkeypatch.setattr(doctor, "_wait_for_ollama_server", lambda: True)
    results = [
        _present("homebrew", "manual"),
        _present("ollama", "system"),
        _missing("ollama-server", "system", [["brew", "services", "start", "ollama"]], critical=True),
        _missing("bge-m3", "local", [["ollama", "pull", "bge-m3"]], critical=True),
    ]
    report = doctor.fix_all(results)
    server_item = next(i for i in report if i["name"] == "ollama-server")
    bge_item = next(i for i in report if i["name"] == "bge-m3")
    assert server_item["action"] == "failed"
    assert bge_item["action"] == "blocked"
    assert "ollama-server" in bge_item.get("detail", "")
    assert ["ollama", "pull", "bge-m3"] not in recorder.calls


def test_fix_all_blocks_venv_and_graphify_when_python312_fails(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/brew")
    recorder = _FailingForRunRecorder(lambda argv: argv[:3] == ["brew", "install", "python@3.12"])
    monkeypatch.setattr(doctor.subprocess, "run", recorder)
    results = [
        _present("homebrew", "manual"),
        _missing("python3.12", "system", [["brew", "install", "python@3.12"]]),
        _missing("venv", "local", [["python3.12", "-m", "venv", ".venv"]], critical=True),
        _missing("graphify", "local", [["python3.12", "-m", "pip", "install", "--user", "graphifyy"]]),
    ]
    report = doctor.fix_all(results)
    py_item = next(i for i in report if i["name"] == "python3.12")
    venv_item = next(i for i in report if i["name"] == "venv")
    graphify_item = next(i for i in report if i["name"] == "graphify")
    assert py_item["action"] == "failed"
    assert venv_item["action"] == "blocked"
    assert graphify_item["action"] == "blocked"
    assert "python3.12" in venv_item.get("detail", "")
    assert "python3.12" in graphify_item.get("detail", "")
    assert ["python3.12", "-m", "venv", ".venv"] not in recorder.calls
    assert ["python3.12", "-m", "pip", "install", "--user", "graphifyy"] not in recorder.calls


def test_fix_all_brew_blocked_prereq_blocks_dependents(monkeypatch):
    recorder = _patch_run(monkeypatch)
    results = [
        _missing("homebrew", "manual", []),
        _missing("ollama", "system", [["brew", "install", "ollama"]]),
        _missing("ollama-server", "system", [["brew", "services", "start", "ollama"]], critical=True),
        _missing("bge-m3", "local", [["ollama", "pull", "bge-m3"]], critical=True),
    ]
    report = doctor.fix_all(results)
    assert recorder.calls == []
    server_item = next(i for i in report if i["name"] == "ollama-server")
    bge_item = next(i for i in report if i["name"] == "bge-m3")
    assert server_item["action"] == "blocked"
    assert bge_item["action"] == "blocked"


def test_wait_for_ollama_server_polls_until_up(monkeypatch):
    states = iter([False, False, True])
    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda: next(states))
    monkeypatch.setattr(doctor.time, "sleep", lambda s: None)
    assert doctor._wait_for_ollama_server() is True


def test_wait_for_ollama_server_times_out(monkeypatch):
    monkeypatch.setattr(doctor, "_probe_ollama_server", lambda: False)
    sleeps = []
    monkeypatch.setattr(doctor.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(doctor, "SERVER_POLL_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(doctor, "SERVER_POLL_INTERVAL_SECONDS", 1.0)
    assert doctor._wait_for_ollama_server() is False
    assert len(sleeps) >= 1
