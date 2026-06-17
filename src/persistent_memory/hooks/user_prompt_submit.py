"""UserPromptSubmit hook — per-prompt recall plus the 5-message extract pulse.

Thin signal layer with two duties: inject a prompt-scoped recall block as
context, and advance the per-project message counter, signalling the daemon to
extract once every EXTRACT_TRIGGER_INTERVAL prompts. Both paths degrade to a
no-op on failure; the hook always exits 0.
"""

import os
import sys

import httpx

from persistent_memory.hooks import common
from persistent_memory.hooks.common import (
    DAEMON_BASE_URL,
    DEFAULT_STATE_DIR,  # re-exported for test backward compatibility
    build_project_key,
    detect_host,
    emit_context,
    extract_prompt_text,
    increment_message_counter,
    post_daemon_signal,
    read_hook_payload,
    reset_message_counter,
    state_dir_for_host,
    transcript_path_from_payload,
)

EXTRACT_TRIGGER_INTERVAL = 5
EXTRACT_ENDPOINT = "/api/extract"
PROMPT_RECALL_ENDPOINT = "/api/prompt-recall"
PROMPT_RECALL_HTTP_TIMEOUT_SECONDS = 2.0
HOOK_EVENT_NAME = "UserPromptSubmit"


def fetch_prompt_recall_block(prompt: str, project: str) -> str:
    response = httpx.get(
        f"{DAEMON_BASE_URL}{PROMPT_RECALL_ENDPOINT}",
        params={"q": prompt, "project": project},
        timeout=PROMPT_RECALL_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return ""
    return response.json().get("block", "")


def _inject_recall(prompt: str, project: str, host: common.Host) -> None:
    if not prompt:
        return
    try:
        block = fetch_prompt_recall_block(prompt=prompt, project=project)
    except (httpx.HTTPError, OSError, ValueError, RuntimeError):
        return
    if block:
        emit_context(block, host=host, event_name=HOOK_EVENT_NAME)


def _advance_extraction(
    payload: dict, *, cwd: str, project_key: str, host: common.Host
) -> None:
    state_dir = state_dir_for_host(host)
    count = increment_message_counter(project_key, state_dir=state_dir)
    if count < EXTRACT_TRIGGER_INTERVAL:
        return
    project, branch = common.derive_project_and_branch(cwd)
    signal_body: dict = {
        "project": project,
        "cwd": cwd,
        "session_id": payload.get("session_id"),
        "transcript_path": transcript_path_from_payload(payload),
    }
    if branch is not None:
        signal_body["branch"] = branch
    post_daemon_signal(EXTRACT_ENDPOINT, signal_body)
    reset_message_counter(project_key, state_dir=state_dir)


def main() -> int:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or os.getcwd()
    host = detect_host(payload)
    project_key = build_project_key(cwd)
    project, _branch = common.derive_project_and_branch(cwd)
    _inject_recall(extract_prompt_text(payload), project, host)
    _advance_extraction(payload, cwd=cwd, project_key=project_key, host=host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
