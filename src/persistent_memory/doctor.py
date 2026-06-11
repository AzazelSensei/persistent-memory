"""Prerequisite doctor: scan, report, and auto-fix the local setup.

Checks the tools persistent-memory depends on (python3.12, venv, ollama +
bge-m3, jq, graphify, claude CLI, claude-mem, git) and can run the fix
commands in dependency order.

Constraint: this module must stay stdlib-only. It runs as an install.sh
preflight under a bare `python3` before any virtualenv exists, so importing
httpx, pydantic, or anything else from the package's dependency set is not
allowed (enforced by tests/test_doctor_stdlib_only.py).
"""

import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_PROBE_TIMEOUT_SECONDS = 2.0
OLLAMA_LIST_TIMEOUT_SECONDS = 10.0
SESSION_START_PROBE_TIMEOUT_SECONDS = 2.5
PYTHON312_BIN = "python3.12"
PYTHON312_BREW_OPT = "/opt/homebrew/opt/python@3.12/bin/python3.12"
EMBED_MODEL = "bge-m3"
GRAPHIFY_PYPI_NAME = "graphifyy"
CLAUDE_MEM_DB = Path.home() / ".claude-mem" / "claude-mem.db"
CLAUDE_MEM_PLUGIN_DIR = Path.home() / ".claude" / "plugins" / "claude-mem"
SERVER_POLL_TIMEOUT_SECONDS = 30.0
SERVER_POLL_INTERVAL_SECONDS = 1.0

Category = Literal["local", "system", "manual"]
OLLAMA_OK_STATUS = 200


@dataclass
class CheckResult:
    name: str
    present: bool
    detail: str
    category: Category
    fix_commands: list[list[str]] = field(default_factory=list)
    critical: bool = False


def _python312_path() -> str | None:
    found = shutil.which(PYTHON312_BIN)
    if found:
        return found
    if Path(PYTHON312_BREW_OPT).exists():
        return PYTHON312_BREW_OPT
    return None


def _probe_ollama_server(timeout: float = OLLAMA_PROBE_TIMEOUT_SECONDS) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=timeout) as response:
            return getattr(response, "status", None) == OLLAMA_OK_STATUS
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _ollama_has_model(model: str, timeout: float = OLLAMA_LIST_TIMEOUT_SECONDS) -> bool:
    binary = shutil.which("ollama")
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, "list"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return model in result.stdout


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ".venv" / "bin" / "python"


def _can_import_in_venv(
    venv_dir: Path, module: str, timeout: float = OLLAMA_LIST_TIMEOUT_SECONDS
) -> bool:
    python = _venv_python(venv_dir)
    if not python.exists():
        return False
    try:
        result = subprocess.run(
            [str(python), "-c", f"import {module}"],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _can_import_python312(module: str) -> bool:
    python = _python312_path()
    if not python:
        return False
    try:
        result = subprocess.run(
            [python, "-c", f"import {module}"],
            capture_output=True,
            timeout=OLLAMA_LIST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _claude_mem_present() -> bool:
    return CLAUDE_MEM_DB.exists() or CLAUDE_MEM_PLUGIN_DIR.exists()


def _check_homebrew() -> CheckResult:
    found = shutil.which("brew")
    return CheckResult(
        name="homebrew",
        present=bool(found),
        detail=found or "brew not found — install manually from https://brew.sh",
        category="manual",
        fix_commands=[],
        critical=False,
    )


def _check_jq() -> CheckResult:
    found = shutil.which("jq")
    return CheckResult(
        name="jq",
        present=bool(found),
        detail=found or "jq not found",
        category="system",
        fix_commands=[["brew", "install", "jq"]],
        critical=False,
    )


def _check_python312() -> CheckResult:
    found = _python312_path()
    return CheckResult(
        name="python3.12",
        present=bool(found),
        detail=found or "python3.12 not found",
        category="system",
        fix_commands=[["brew", "install", "python@3.12"]],
        critical=False,
    )


def _check_venv(records_dir: Path) -> CheckResult:
    present = _can_import_in_venv(records_dir, "persistent_memory", timeout=OLLAMA_LIST_TIMEOUT_SECONDS)
    return CheckResult(
        name="venv",
        present=present,
        detail="venv ready" if present else ".venv/bin/python cannot import persistent_memory",
        category="local",
        fix_commands=[
            [PYTHON312_BIN, "-m", "venv", ".venv"],
            [".venv/bin/python", "-m", "pip", "install", "-e", ".[daemon]"],
        ],
        critical=True,
    )


def _check_ollama_binary() -> CheckResult:
    found = shutil.which("ollama")
    return CheckResult(
        name="ollama",
        present=bool(found),
        detail=found or "ollama not found",
        category="system",
        fix_commands=[["brew", "install", "ollama"]],
        critical=False,
    )


def _check_ollama_server() -> CheckResult:
    present = _probe_ollama_server()
    return CheckResult(
        name="ollama-server",
        present=present,
        detail="ollama server is running" if present else "ollama server is down (:11434)",
        category="system",
        fix_commands=[["brew", "services", "start", "ollama"]],
        critical=True,
    )


def _check_bge_m3() -> CheckResult:
    present = _ollama_has_model(EMBED_MODEL, timeout=OLLAMA_LIST_TIMEOUT_SECONDS)
    return CheckResult(
        name="bge-m3",
        present=present,
        detail="bge-m3 present" if present else "bge-m3 model not pulled (~1.2GB)",
        category="local",
        fix_commands=[["ollama", "pull", EMBED_MODEL]],
        critical=True,
    )


def _check_graphify() -> CheckResult:
    present = _can_import_python312("graphify")
    return CheckResult(
        name="graphify",
        present=present,
        detail="graphify is importable" if present else "graphify (python3.12) not found",
        category="local",
        fix_commands=[[PYTHON312_BIN, "-m", "pip", "install", "--user", GRAPHIFY_PYPI_NAME]],
        critical=False,
    )


def _check_claude_cli() -> CheckResult:
    found = shutil.which("claude")
    return CheckResult(
        name="claude",
        present=bool(found),
        detail=found or "claude CLI not found — install Claude Code manually",
        category="manual",
        fix_commands=[],
        critical=False,
    )


def _check_claude_mem() -> CheckResult:
    present = _claude_mem_present()
    return CheckResult(
        name="claude-mem",
        present=present,
        detail="claude-mem present" if present else "claude-mem not found — install manually",
        category="manual",
        fix_commands=[],
        critical=False,
    )


def _check_git() -> CheckResult:
    found = shutil.which("git")
    return CheckResult(
        name="git",
        present=bool(found),
        detail=found or "git not found",
        category="manual",
        fix_commands=[],
        critical=False,
    )


FIX_ORDER = [
    "jq",
    "python3.12",
    "venv",
    "ollama",
    "ollama-server",
    "bge-m3",
    "graphify",
]
FIX_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "ollama-server": ("ollama",),
    "bge-m3": ("ollama", "ollama-server"),
    "graphify": ("python3.12",),
    "venv": ("python3.12",),
}
FIXABLE_CATEGORIES = ("local", "system")
COMMAND_TIMEOUT_SECONDS = 1800


def _wait_for_ollama_server() -> bool:
    attempts = max(1, int(SERVER_POLL_TIMEOUT_SECONDS / SERVER_POLL_INTERVAL_SECONDS))
    for _ in range(attempts):
        if _probe_ollama_server():
            return True
        time.sleep(SERVER_POLL_INTERVAL_SECONDS)
    return _probe_ollama_server()


def _run_command(argv: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "").strip()
    return True, (result.stdout or "").strip()


def _is_brew_present(results: list[CheckResult]) -> bool:
    for result in results:
        if result.name == "homebrew":
            return result.present
    return bool(shutil.which("brew"))


def _log(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def _blocking_prereq(name: str, failed_or_blocked: set[str]) -> str | None:
    for prereq in FIX_PREREQUISITES.get(name, ()):
        if prereq in failed_or_blocked:
            return prereq
    return None


def fix_all(results: list[CheckResult], *, dry_run: bool = False) -> list[dict]:
    by_name = {result.name: result for result in results}
    brew_present = _is_brew_present(results)
    failed_or_blocked: set[str] = set()
    report: list[dict] = []

    for name in FIX_ORDER:
        result = by_name.get(name)
        if result is None:
            continue
        if result.present:
            report.append({"name": name, "action": "skipped", "commands": []})
            continue
        if result.category not in FIXABLE_CATEGORIES:
            report.append({"name": name, "action": "manual", "commands": result.fix_commands})
            continue
        blocking = _blocking_prereq(name, failed_or_blocked)
        if blocking is not None:
            _log(f"[doctor] {name}: {blocking} could not be fixed, skipped")
            failed_or_blocked.add(name)
            report.append(
                {
                    "name": name,
                    "action": "blocked",
                    "commands": result.fix_commands,
                    "detail": f"{blocking} prerequisite failed",
                }
            )
            continue
        if result.category == "system" and not brew_present:
            _log(f"[doctor] {name}: brew missing, system fix skipped")
            failed_or_blocked.add(name)
            report.append({"name": name, "action": "blocked", "commands": result.fix_commands})
            continue
        if dry_run:
            _log(f"[doctor] PLAN {name}: {result.fix_commands}")
            report.append({"name": name, "action": "planned", "commands": result.fix_commands})
            continue
        item = _apply_fix(name, result)
        if item["action"] == "failed":
            failed_or_blocked.add(name)
        report.append(item)

    for result in results:
        if result.name not in FIX_ORDER and not result.present:
            report.append({"name": result.name, "action": "manual", "commands": result.fix_commands})

    return report


def _apply_fix(name: str, result: CheckResult) -> dict:
    for argv in result.fix_commands:
        _log(f"[doctor] {name}: {' '.join(argv)}")
        ok, detail = _run_command(argv)
        if not ok:
            _log(f"[doctor] {name}: ERROR — {detail}")
            return {"name": name, "action": "failed", "commands": result.fix_commands, "detail": detail}
    if name == "ollama-server":
        if not _wait_for_ollama_server():
            _log(f"[doctor] {name}: server did not come up on :11434")
            return {"name": name, "action": "failed", "commands": result.fix_commands, "detail": "server timeout"}
    _log(f"[doctor] {name}: done")
    return {"name": name, "action": "fixed", "commands": result.fix_commands}


CHECK_FLAGS = ("--check",)
DRY_RUN_FLAGS = ("--dry-run",)
STATUS_PRESENT = "OK"
STATUS_MISSING = "MISSING"


def _print_scan_summary(results: list["CheckResult"]) -> None:
    _log("persistent-memory doctor — prerequisite scan")
    for result in results:
        marker = STATUS_PRESENT if result.present else STATUS_MISSING
        flag = " [critical]" if result.critical and not result.present else ""
        _log(f"  [{marker}] {result.name}{flag}: {result.detail}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    is_check = any(arg in CHECK_FLAGS for arg in args)
    is_dry_run = any(arg in DRY_RUN_FLAGS for arg in args)
    results = scan()
    _print_scan_summary(results)
    if is_check:
        return 0
    report = fix_all(results, dry_run=is_dry_run)
    for item in report:
        _log(f"  -> {item['name']}: {item['action']}")
    return 0


def detect_missing_critical(records_dir: Path | str | None = None) -> list[str]:
    base = Path(records_dir) if records_dir is not None else REPO_ROOT
    timeout = SESSION_START_PROBE_TIMEOUT_SECONDS
    missing: list[str] = []
    if not _probe_ollama_server(timeout=timeout):
        missing.append("ollama-server")
    if not _ollama_has_model(EMBED_MODEL, timeout=timeout):
        missing.append("bge-m3")
    if not _can_import_in_venv(base, "persistent_memory", timeout=timeout):
        missing.append("venv")
    return missing


def scan(records_dir: Path | str | None = None) -> list[CheckResult]:
    base = Path(records_dir) if records_dir is not None else REPO_ROOT
    return [
        _check_homebrew(),
        _check_jq(),
        _check_python312(),
        _check_venv(base),
        _check_ollama_binary(),
        _check_ollama_server(),
        _check_bge_m3(),
        _check_graphify(),
        _check_claude_cli(),
        _check_claude_mem(),
        _check_git(),
    ]


if __name__ == "__main__":
    sys.exit(main())
