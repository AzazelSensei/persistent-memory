"""PreToolUse hook — model-guard for subagent dispatch.

Blocks Agent/Task calls that lack an explicit model, injecting the pinning
rule as permissionDecisionReason so the agent sees it and re-dispatches with
the correct model. All other tools pass through silently.

Workflow is guarded by a weaker tripwire: the model lives inside the script
body rather than in a tool parameter, so the hook only checks whether ANY pin
is present — it deliberately does not count agent() calls against model:
occurrences, because that is lexically unreliable (comments, strings,
meta.phases[].model, helper wrappers). A script that cannot be read fails
OPEN: this guard exists to catch forgetting, not an attacker, and a false deny
would push the user to set PM_DISABLE_MODEL_GUARD=1 and lose the working
Agent/Task guard with it.

Always exits 0; the hook runtime must stay well under the 5-second timeout.
"""

import json
import os
import re
import sys
from pathlib import Path

import httpx

from persistent_memory.hooks.common import (
    DAEMON_BASE_URL,
    project_name,
    read_hook_payload,
)

GUARDED_TOOLS = frozenset({"Agent", "Task"})
WORKFLOW_TOOL = "Workflow"
RECALL_QUERY = "subagent model cost dispatch"
RECALL_HTTP_TIMEOUT_SECONDS = 1.5
RECALL_MAX_CHARS = 800
HOOK_EVENT_NAME = "PreToolUse"
PROMPT_RECALL_ENDPOINT = "/api/prompt-recall"

SCRIPT_MAX_BYTES = 512 * 1024
AGENT_CALL_RE = re.compile(r"\bagent\s*\(")
MODEL_PIN_RE = re.compile(r"""["']?\bmodel\b["']?\s*:\s*["']""")
MODEL_SHORTHAND_RE = re.compile(r"[{,]\s*model\s*[,}]")
META_DECL_RE = re.compile(r"\bexport\s+const\s+meta\s*=\s*\{")
OPEN_BRACE = "{"
CLOSE_BRACE = "}"

_TIER_RULE = (
    "Choose per the task (decide opus-vs-sonnet consciously — do NOT reflexively "
    "default to sonnet): genuine reasoning (architecture / hard debug / deep or "
    "adversarial analysis / complex synthesis / planning) → \"opus\"; mechanical "
    "implementation / translation / cleanup / spec-driven TDD / review → \"sonnet\"; "
    "read-only scan / inventory / exploration → \"haiku\"."
)

_DENY_REASON = (
    "Model-guard: you must supply an explicit `model` parameter when dispatching "
    f"a subagent. {_TIER_RULE} "
    "Re-dispatch the same call with `model` set. "
    "Disable this guard: PM_DISABLE_MODEL_GUARD=1."
)

_WORKFLOW_DENY_REASON = (
    "Model-guard: this Workflow script dispatches agent() without pinning a model. "
    "Pass opts.model on every agent() call. The Workflow tool's own advice to omit "
    "the model and inherit the session model does NOT apply here — an omitted model "
    "runs mechanical fan-out on the flagship tier, increasing the cost of a "
    f"mechanical job. {_TIER_RULE} "
    "Re-dispatch with model set on each agent() call. "
    "Disable this guard: PM_DISABLE_MODEL_GUARD=1."
)


def fetch_memory_recall(q: str, project: str) -> str:
    response = httpx.get(
        f"{DAEMON_BASE_URL}{PROMPT_RECALL_ENDPOINT}",
        params={"q": q, "project": project},
        timeout=RECALL_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return ""
    return response.json().get("block", "")


def _build_deny_reason(cwd: str, base: str = _DENY_REASON) -> str:
    reason = base
    try:
        block = fetch_memory_recall(RECALL_QUERY, project_name(cwd))
    except (httpx.HTTPError, OSError, ValueError, RuntimeError):
        block = ""
    if block:
        suffix = block[:RECALL_MAX_CHARS]
        reason = f"{reason}\n\nRelated memory:\n{suffix}"
    return reason


def _workflow_script_text(tool_input: dict) -> str | None:
    """Script body for a Workflow call, or None when it cannot be read."""
    script = tool_input.get("script")
    if isinstance(script, str) and script.strip():
        return script

    path_value = tool_input.get("scriptPath")
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    try:
        path = Path(path_value)
        if not path.is_file():
            return None
        if path.stat().st_size > SCRIPT_MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _strip_meta_block(text: str) -> str:
    """Drop `export const meta = {...}`; its phases[].model is not a pin."""
    match = META_DECL_RE.search(text)
    if not match:
        return text
    depth = 0
    for index in range(match.end() - 1, len(text)):
        char = text[index]
        if char == OPEN_BRACE:
            depth += 1
        elif char == CLOSE_BRACE:
            depth -= 1
            if depth == 0:
                return text[: match.start()] + text[index + 1 :]
    return text[: match.start()]


def _has_model_pin(text: str) -> bool:
    return bool(MODEL_PIN_RE.search(text) or MODEL_SHORTHAND_RE.search(text))


def _workflow_missing_pin(tool_input: dict) -> bool:
    text = _workflow_script_text(tool_input)
    if text is None:
        return False
    if not AGENT_CALL_RE.search(text):
        return False
    return not _has_model_pin(_strip_meta_block(text))


def _emit_deny(reason: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))


def main() -> int:
    if os.environ.get("PM_DISABLE_MODEL_GUARD") == "1":
        return 0

    payload = read_hook_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name == WORKFLOW_TOOL:
        if not _workflow_missing_pin(tool_input):
            return 0
        cwd = payload.get("cwd") or os.getcwd()
        _emit_deny(_build_deny_reason(cwd, _WORKFLOW_DENY_REASON))
        return 0

    if tool_name not in GUARDED_TOOLS:
        return 0

    model = tool_input.get("model", "")
    if model and isinstance(model, str) and model.strip():
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    _emit_deny(_build_deny_reason(cwd))
    return 0


if __name__ == "__main__":
    sys.exit(main())
