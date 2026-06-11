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
from persistent_memory.i18n import t

RECALL_ENDPOINT = "/api/recall"
RECALL_HTTP_TIMEOUT_SECONDS = 3.0
HOOK_EVENT_NAME = "SessionStart"
# Warning text is resolved at call time via i18n.t so PM_LANG applies per process.
CRITICAL_LABEL_KEYS = {
    "ollama-server": "session_start.critical.ollama_server",
    "bge-m3": "session_start.critical.bge_m3",
    "venv": "session_start.critical.venv",
}
DOCTOR_HINT_KEY = "session_start.doctor_hint"


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


def _critical_label(name: str) -> str:
    key = CRITICAL_LABEL_KEYS.get(name)
    if key is None:
        return name
    return t(key)


def _build_warning() -> str:
    try:
        missing = detect_missing_critical()
    except Exception:
        return ""
    if not missing:
        return ""
    labels = ", ".join(_critical_label(name) for name in missing)
    return f"⚠️ persistent-memory: {labels} — {t(DOCTOR_HINT_KEY)}"


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
