"""Shared plumbing for the Claude Code / Codex / Kimi hook entrypoints.

Hooks are a thin signal layer: they parse the hook payload from stdin, keep a
tiny per-project message counter on disk, and fire short-timeout HTTP signals
at the local daemon. All heavy work (extraction, retrieval, indexing) lives in
the daemon; a hook must never block or fail the host session, so every network
error degrades to a no-op and the process exits 0.
"""

import enum
import hashlib
import json
import os
import subprocess
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


class Host(enum.Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    KIMI = "kimi"


def detect_host(payload: dict) -> Host:
    """Identify the host CLI from the hook payload.

    Kimi Code CLI uses snake_case keys and exposes ``session_dir``; Claude and
    Codex share the same JSON envelope, so they both map to ``Host.CLAUDE``.
    """
    if payload.get("session_dir"):
        return Host.KIMI
    return Host.CLAUDE


def state_dir_for_host(host: Host) -> Path:
    """Return the per-host state directory for message counters."""
    if host is Host.KIMI:
        return Path.home() / ".kimi-code" / "persistent-memory" / "hook-state"
    return DEFAULT_STATE_DIR


def emit_context(text: str, host: Host, event_name: str) -> None:
    """Emit a recall/context block in the format expected by the host CLI.

    - Claude/Codex: JSON envelope with ``hookSpecificOutput.additionalContext``.
    - Kimi: plain stdout text (the runner appends it to the agent context).
    """
    if host is Host.KIMI:
        sys.stdout.write(text)
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }
    sys.stdout.write(json.dumps(payload))


def extract_prompt_text(payload: dict) -> str:
    """Extract the user's prompt text from a host-specific payload.

    Kimi passes ``prompt`` as a list of ContentParts; Claude/Codex pass a string
    or a ``message`` object.
    """
    prompt = payload.get("prompt")
    if isinstance(prompt, list):
        texts = [
            str(part.get("text", ""))
            for part in prompt
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return " ".join(text for text in texts if text).strip()
    if isinstance(prompt, str):
        return prompt.strip()
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def transcript_path_from_payload(payload: dict) -> str | None:
    """Return a transcript path for the daemon, if one can be determined.

    Kimi exposes ``session_dir``; the active agent wire log lives at
    ``<session_dir>/agents/main/wire.jsonl``.
    """
    explicit = payload.get("transcript_path")
    if explicit:
        return explicit
    session_dir = payload.get("session_dir")
    if session_dir:
        path = Path(session_dir) / "agents" / "main" / "wire.jsonl"
        if path.is_file():
            return str(path)
    return None


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


def _git_run(args: list[str], cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _current_branch(cwd: str) -> str | None:
    return _git_run(["rev-parse", "--abbrev-ref", "HEAD"], cwd)


def _is_worktree_root(cwd: str) -> bool:
    git_dir = _git_run(["rev-parse", "--git-dir"], cwd)
    common_dir = _git_run(["rev-parse", "--git-common-dir"], cwd)
    if not git_dir or not common_dir:
        return False
    if git_dir == common_dir:
        return False
    toplevel = _git_run(["rev-parse", "--show-toplevel"], cwd)
    if not toplevel:
        return False
    return Path(cwd).resolve() == Path(toplevel).resolve()


def _main_repo_name_from_worktree(cwd: str) -> str | None:
    common_dir = _git_run(["rev-parse", "--git-common-dir"], cwd)
    if not common_dir:
        return None
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = (Path(cwd) / common_path).resolve()
    return common_path.parent.name or None


def derive_project_and_branch(cwd: str) -> tuple[str, str | None]:
    """Derive (project_name, branch) from a working directory.

    Rules:
    - If cwd is the root of a git linked worktree: project = main repo name,
      branch = current worktree branch.
    - Any other case: project = basename(cwd) (existing behaviour preserved),
      branch = current git branch if inside a git repo, else None.
    - git failures are silent: returns (basename, None).
    """
    if not cwd:
        return "unknown", None

    branch = _current_branch(cwd)

    if branch is not None and _is_worktree_root(cwd):
        main_name = _main_repo_name_from_worktree(cwd)
        project = main_name if main_name else project_name(cwd)
        return project, branch

    return project_name(cwd), branch


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
