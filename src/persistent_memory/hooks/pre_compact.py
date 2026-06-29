"""PreCompact hook — flush pending extraction before context is compacted.

Thin signal layer: posts a single flush signal to the daemon's extract
endpoint and resets the message counter. Always exits 0.
"""

import os
import sys

from persistent_memory.hooks import common
from persistent_memory.hooks.common import (
    build_project_key,
    detect_host,
    derive_project_and_branch,
    post_daemon_signal,
    read_hook_payload,
    reset_message_counter,
    state_dir_for_host,
    transcript_path_from_payload,
)

EXTRACT_ENDPOINT = "/api/extract"
COMPACT_REASON = "pre_compact"


def main() -> int:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or os.getcwd()
    host = detect_host(payload)
    state_dir = state_dir_for_host(host)
    project_key = build_project_key(cwd)
    project, branch = common.derive_project_and_branch(cwd)
    signal_body: dict = {
        "project": project,
        "cwd": cwd,
        "session_id": payload.get("session_id"),
        "transcript_path": transcript_path_from_payload(payload),
        "flush": True,
        "reason": COMPACT_REASON,
    }
    if branch is not None:
        signal_body["branch"] = branch
    post_daemon_signal(EXTRACT_ENDPOINT, signal_body)
    reset_message_counter(project_key, state_dir=state_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
