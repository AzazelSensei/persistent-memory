"""PreToolUse hook — model-guard for subagent dispatch.

Blocks Agent/Task calls that lack an explicit model, injecting the pinning
rule as permissionDecisionReason so the agent sees it and re-dispatches with
the correct model. All other tools pass through silently.

Always exits 0; the hook runtime must stay well under the 5-second timeout.
"""

import json
import os
import sys

import httpx

from persistent_memory.hooks.common import (
    DAEMON_BASE_URL,
    project_name,
    read_hook_payload,
)

GUARDED_TOOLS = frozenset({"Agent", "Task"})
RECALL_QUERY = "subagent model cost dispatch"
RECALL_HTTP_TIMEOUT_SECONDS = 1.5
RECALL_MAX_CHARS = 800
HOOK_EVENT_NAME = "PreToolUse"
PROMPT_RECALL_ENDPOINT = "/api/prompt-recall"

_DENY_REASON = (
    "Model-guard: you must supply an explicit `model` parameter when dispatching "
    "a subagent. Rules: mechanical implementation / translation / cleanup / "
    "spec-driven TDD / review → \"sonnet\"; read-only scan / inventory / "
    "exploration → \"haiku\"; flagship only as a deliberate choice. "
    "Re-dispatch the same call with `model` set. "
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


def _build_deny_reason(cwd: str) -> str:
    reason = _DENY_REASON
    try:
        block = fetch_memory_recall(RECALL_QUERY, project_name(cwd))
    except (httpx.HTTPError, OSError, ValueError, RuntimeError):
        block = ""
    if block:
        suffix = block[:RECALL_MAX_CHARS]
        reason = f"{reason}\n\nRelated memory:\n{suffix}"
    return reason


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

    if tool_name not in GUARDED_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or {}
    model = tool_input.get("model", "")
    if model and isinstance(model, str) and model.strip():
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    _emit_deny(_build_deny_reason(cwd))
    return 0


if __name__ == "__main__":
    sys.exit(main())
