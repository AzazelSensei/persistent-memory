"""CLI call layer for the AI Council: clean env, argv builders, answer extraction.

Backend bin resolution mirrors `daemon/services.py`'s `_resolve_*_bin`
functions exactly (that file is out of scope for Council changes, so the
logic is duplicated here and this module is the single source going
forward). Argv construction is council-specific and does NOT reuse the
extraction argv builders in `extraction_prompt.py`. Council uses its own
CLI flags; see the README for their permissions and provider boundaries.
"""

import json
import os
import shutil
from pathlib import Path

from persistent_memory.council.config import COUNCIL_BACKENDS
from persistent_memory.extraction_prompt import (
    CLAUDE_BIN,
    CODEX_APP_BIN,
    CODEX_BIN,
    CODEX_BIN_ENV,
    GROK_BIN,
    GROK_BIN_ENV,
    GROK_HOME_BIN,
    GROK_USER_BIN,
    KIMI_BIN,
)

COUNCIL_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SHELL")
PM_ENV_PREFIX = "PM_"
COUNCIL_READONLY_ENV = "PM_COUNCIL_READONLY"
COUNCIL_EXTRA_PATHS = (
    Path.home() / ".local" / "bin",
    Path.home() / ".grok" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)

CLAUDE_PERMISSION_MODE = "bypassPermissions"
CLAUDE_OUTPUT_FORMAT = "json"
CODEX_REASONING_EFFORT_KEY = "model_reasoning_effort"
KIMI_OUTPUT_FORMAT = "text"
GROK_OUTPUT_FORMAT = "plain"


class CouncilBackendError(ValueError):
    pass


def build_council_env() -> dict:
    env: dict[str, str] = {}
    for key in COUNCIL_ENV_ALLOWLIST:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    for key, value in os.environ.items():
        if key.startswith(PM_ENV_PREFIX):
            env[key] = value

    extra = os.pathsep.join(str(path) for path in COUNCIL_EXTRA_PATHS if path.is_dir())
    if extra:
        env["PATH"] = os.pathsep.join(filter(None, [extra, env.get("PATH", "")]))
    env[COUNCIL_READONLY_ENV] = "1"
    return env


def _resolve_claude_bin(env: dict) -> str:
    return shutil.which(CLAUDE_BIN, path=env.get("PATH")) or CLAUDE_BIN


def _resolve_codex_bin(env: dict) -> str | None:
    override = env.get(CODEX_BIN_ENV)
    if override:
        return override
    if CODEX_APP_BIN.is_file():
        return str(CODEX_APP_BIN)
    return shutil.which(CODEX_BIN, path=env.get("PATH"))


def _resolve_kimi_bin(env: dict) -> str | None:
    return shutil.which(KIMI_BIN, path=env.get("PATH"))


def _resolve_grok_bin(env: dict) -> str | None:
    override = env.get(GROK_BIN_ENV)
    if override:
        return override
    for candidate in (GROK_USER_BIN, GROK_HOME_BIN):
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return shutil.which(GROK_BIN, path=env.get("PATH"))


def resolve_backend_bin(backend: str, env: dict | None = None) -> str | None:
    resolved_env = env if env is not None else build_council_env()
    if backend == "claude":
        return _resolve_claude_bin(resolved_env)
    if backend == "codex":
        return _resolve_codex_bin(resolved_env)
    if backend == "kimi":
        return _resolve_kimi_bin(resolved_env)
    if backend == "grok":
        return _resolve_grok_bin(resolved_env)
    raise CouncilBackendError(f"unknown council backend {backend!r}, must be one of {COUNCIL_BACKENDS}")


def _build_claude_argv(prompt: str, cwd: str, model: str | None, effort: str | None) -> list[str]:
    argv = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--permission-mode",
        CLAUDE_PERMISSION_MODE,
        "--output-format",
        CLAUDE_OUTPUT_FORMAT,
    ]
    if model:
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    argv.extend(["--add-dir", cwd])
    return argv


def _build_codex_argv(prompt: str, cwd: str, model: str | None, effort: str | None) -> list[str]:
    argv = [
        CODEX_BIN,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        cwd,
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    if model:
        argv.extend(["-m", model])
    if effort:
        argv.extend(["-c", f"{CODEX_REASONING_EFFORT_KEY}={json.dumps(effort)}"])
    argv.append(prompt)
    return argv


def _build_kimi_argv(prompt: str, model: str | None) -> list[str]:
    argv = [KIMI_BIN, "-p", prompt, "--output-format", KIMI_OUTPUT_FORMAT]
    if model:
        argv.extend(["-m", model])
    return argv


def _build_grok_argv(prompt: str, cwd: str, model: str | None, effort: str | None) -> list[str]:
    argv = [
        GROK_BIN,
        "-p",
        prompt,
        "--always-approve",
        "--output-format",
        GROK_OUTPUT_FORMAT,
        "--no-subagents",
    ]
    if effort:
        argv.extend(["--effort", effort])
    if model:
        argv.extend(["-m", model])
    argv.extend(["--cwd", cwd])
    return argv


def build_council_argv(
    backend: str,
    prompt: str,
    cwd: str,
    model: str | None = None,
    effort: str | None = None,
) -> list[str]:
    if backend == "claude":
        return _build_claude_argv(prompt, cwd, model, effort)
    if backend == "codex":
        return _build_codex_argv(prompt, cwd, model, effort)
    if backend == "kimi":
        return _build_kimi_argv(prompt, model)
    if backend == "grok":
        return _build_grok_argv(prompt, cwd, model, effort)
    raise CouncilBackendError(f"unknown council backend {backend!r}, must be one of {COUNCIL_BACKENDS}")


CODEX_TAG_LINE = "codex"


def _extract_claude_answer(stdout_text: str) -> str:
    stripped = stdout_text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped

    candidates = data if isinstance(data, list) else [data]
    for item in candidates:
        if isinstance(item, dict) and item.get("type") == "result":
            result = item.get("result")
            if isinstance(result, str):
                return result.strip()
    return stripped


def _extract_codex_answer(stdout_text: str) -> str:
    lines = stdout_text.splitlines()
    last_tag_index = None
    for index, line in enumerate(lines):
        cleaned = line.strip()
        if cleaned.endswith(CODEX_TAG_LINE) and (
            cleaned == CODEX_TAG_LINE or cleaned[: -len(CODEX_TAG_LINE)].rstrip().endswith("]")
        ):
            last_tag_index = index

    if last_tag_index is not None:
        after = "\n".join(lines[last_tag_index + 1 :]).strip()
        if after:
            return after

    paragraphs = [part.strip() for part in stdout_text.split("\n\n") if part.strip()]
    return paragraphs[-1] if paragraphs else ""


def extract_answer(backend: str, stdout_text: str) -> str:
    if not stdout_text or not stdout_text.strip():
        return ""
    if backend == "claude":
        return _extract_claude_answer(stdout_text)
    if backend == "codex":
        return _extract_codex_answer(stdout_text)
    if backend in ("grok", "kimi"):
        return stdout_text.strip()
    raise CouncilBackendError(f"unknown council backend {backend!r}, must be one of {COUNCIL_BACKENDS}")
