"""SessionStart hook — inject the fixed-budget recall block into new sessions.

Thin signal layer: fetches the project's recall block from the daemon and
emits it as `additionalContext`, prepending a one-line warning when a critical
prerequisite (ollama, bge-m3, venv) is missing. Degrades to silence on any
failure and always exits 0.
"""

import json
import os
import sys

import httpx

from persistent_memory.doctor import detect_missing_critical
from persistent_memory.hooks.common import (
    DAEMON_BASE_URL,
    is_daemon_healthy,
    project_name,
    read_hook_payload,
)

RECALL_ENDPOINT = "/api/recall"
RECALL_HTTP_TIMEOUT_SECONDS = 3.0
HOOK_EVENT_NAME = "SessionStart"
CRITICAL_LABELS = {
    "ollama-server": "ollama server is down",
    "bge-m3": "bge-m3 model is missing",
    "venv": ".venv is not ready",
}
DOCTOR_HINT = "run `/persistent-memory doctor`"


def fetch_recall_block(project: str) -> str:
    response = httpx.get(
        f"{DAEMON_BASE_URL}{RECALL_ENDPOINT}",
        params={"project": project},
        timeout=RECALL_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return ""
    return response.json().get("block", "")


def _emit(additional_context: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "additionalContext": additional_context,
        }
    }
    sys.stdout.write(json.dumps(payload))


def _build_warning() -> str:
    try:
        missing = detect_missing_critical()
    except Exception:
        return ""
    if not missing:
        return ""
    labels = ", ".join(CRITICAL_LABELS.get(name, name) for name in missing)
    return f"⚠️ persistent-memory: {labels} — {DOCTOR_HINT}"


def _prepend_warning(block: str, warning: str) -> str:
    if not warning:
        return block
    if not block:
        return warning
    return f"{warning}\n\n{block}"


def main() -> int:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or os.getcwd()
    warning = _build_warning()
    if not is_daemon_healthy():
        _emit(_prepend_warning("", warning))
        return 0
    try:
        block = fetch_recall_block(project=project_name(cwd))
    except (httpx.HTTPError, OSError, ValueError, RuntimeError):
        block = ""
    _emit(_prepend_warning(block, warning))
    return 0


if __name__ == "__main__":
    sys.exit(main())
