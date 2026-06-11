"""UserPromptSubmit hook — per-prompt recall plus the 5-message extract pulse.

Thin signal layer with two duties: inject a prompt-scoped recall block as
`additionalContext`, and advance the per-project message counter, signalling
the daemon to extract once every EXTRACT_TRIGGER_INTERVAL prompts. Both paths
degrade to a no-op on failure; the hook always exits 0.
"""

import json
import os
import sys

import httpx

from persistent_memory.hooks import common
from persistent_memory.hooks.common import (
    DAEMON_BASE_URL,
    DEFAULT_STATE_DIR,
    build_project_key,
    increment_message_counter,
    project_name,
    post_daemon_signal,
    read_hook_payload,
    reset_message_counter,
)

EXTRACT_TRIGGER_INTERVAL = 5
EXTRACT_ENDPOINT = "/api/extract"
PROMPT_RECALL_ENDPOINT = "/api/prompt-recall"
PROMPT_RECALL_HTTP_TIMEOUT_SECONDS = 2.0
HOOK_EVENT_NAME = "UserPromptSubmit"
PROMPT_KEYS = ("prompt", "user_prompt")


def _extract_prompt_text(payload: dict) -> str:
    for key in PROMPT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return ""


def fetch_prompt_recall_block(prompt: str, project: str) -> str:
    response = httpx.get(
        f"{DAEMON_BASE_URL}{PROMPT_RECALL_ENDPOINT}",
        params={"q": prompt, "project": project},
        timeout=PROMPT_RECALL_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return ""
    return response.json().get("block", "")


def _emit_additional_context(block: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "additionalContext": block,
        }
    }
    sys.stdout.write(json.dumps(payload))


def _inject_recall(prompt: str, project_key: str) -> None:
    if not prompt:
        return
    try:
        block = fetch_prompt_recall_block(prompt=prompt, project=project_key)
    except (httpx.HTTPError, OSError, ValueError, RuntimeError):
        return
    if block:
        _emit_additional_context(block)


def _advance_extraction(payload: dict, *, cwd: str, project_key: str) -> None:
    count = increment_message_counter(project_key, state_dir=common.DEFAULT_STATE_DIR)
    if count < EXTRACT_TRIGGER_INTERVAL:
        return
    post_daemon_signal(
        EXTRACT_ENDPOINT,
        {
            "project": project_name(cwd),
            "cwd": cwd,
            "session_id": payload.get("session_id"),
            "transcript_path": payload.get("transcript_path"),
        },
    )
    reset_message_counter(project_key, state_dir=common.DEFAULT_STATE_DIR)


def main() -> int:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or os.getcwd()
    project_key = build_project_key(cwd)
    _inject_recall(_extract_prompt_text(payload), project_name(cwd))
    _advance_extraction(payload, cwd=cwd, project_key=project_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
