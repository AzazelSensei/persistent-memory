"""Shared plumbing for the Claude Code hook entrypoints.

Hooks are a thin signal layer: they parse the hook payload from stdin, keep a
tiny per-project message counter on disk, and fire short-timeout HTTP signals
at the local daemon. All heavy work (extraction, retrieval, indexing) lives in
the daemon; a hook must never block or fail the host session, so every network
error degrades to a no-op and the process exits 0.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx

from persistent_memory.daemon.token import default_records_dir, read_token

DAEMON_BASE_URL = "http://127.0.0.1:37778"
HEALTH_ENDPOINT = "/api/health"
HOOK_HTTP_TIMEOUT_SECONDS = 2.0
PROJECT_KEY_LENGTH = 16
TOKEN_HEADER = "X-PM-Token"
DEFAULT_STATE_DIR = Path.home() / ".claude" / "persistent-memory" / "hook-state"


def read_hook_payload() -> dict:
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def build_project_key(cwd: str) -> str:
    digest = hashlib.sha256((cwd or "unknown").encode("utf-8")).hexdigest()
    return digest[:PROJECT_KEY_LENGTH]


def project_name(cwd: str) -> str:
    name = Path(cwd or "").name
    return name or "unknown"


def _state_path(project_key: str, state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{project_key}.json"


def _write_state_atomic(path: Path, payload: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_name, path)
    except OSError:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def read_message_counter(project_key: str, state_dir: Path = DEFAULT_STATE_DIR) -> int:
    path = _state_path(project_key, state_dir)
    if not path.exists():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("count", 0))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0


def increment_message_counter(project_key: str, state_dir: Path = DEFAULT_STATE_DIR) -> int:
    path = _state_path(project_key, state_dir)
    current = read_message_counter(project_key, state_dir)
    new_count = current + 1
    _write_state_atomic(path, {"count": new_count})
    return new_count


def reset_message_counter(project_key: str, state_dir: Path = DEFAULT_STATE_DIR) -> None:
    path = _state_path(project_key, state_dir)
    _write_state_atomic(path, {"count": 0})


def _daemon_token_header() -> dict:
    token = read_token(default_records_dir())
    if not token:
        return {}
    return {TOKEN_HEADER: token}


def post_daemon_signal(endpoint: str, body: dict) -> bool:
    try:
        response = httpx.post(
            f"{DAEMON_BASE_URL}{endpoint}",
            json=body,
            headers=_daemon_token_header(),
            timeout=HOOK_HTTP_TIMEOUT_SECONDS,
        )
        return response.status_code < 400
    except (httpx.HTTPError, OSError):
        return False


def is_daemon_healthy() -> bool:
    try:
        response = httpx.get(
            f"{DAEMON_BASE_URL}{HEALTH_ENDPOINT}",
            timeout=HOOK_HTTP_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except (httpx.HTTPError, OSError):
        return False
