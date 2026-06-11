"""Stop/SessionEnd hook — flush leftover messages when a session ends.

Thin signal layer: if the per-project counter shows unprocessed messages, post
one flush signal to the daemon and reset the counter. Always exits 0.
"""

import os
import sys

from persistent_memory.hooks import common
from persistent_memory.hooks.common import (
    build_project_key,
    post_daemon_signal,
    project_name,
    read_hook_payload,
    read_message_counter,
    reset_message_counter,
)

EXTRACT_ENDPOINT = "/api/extract"


def main() -> int:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or os.getcwd()
    project_key = build_project_key(cwd)
    pending = read_message_counter(project_key, state_dir=common.DEFAULT_STATE_DIR)
    if pending <= 0:
        return 0
    post_daemon_signal(
        EXTRACT_ENDPOINT,
        {
            "project": project_name(cwd),
            "cwd": cwd,
            "session_id": payload.get("session_id"),
            "transcript_path": payload.get("transcript_path"),
            "flush": True,
        },
    )
    reset_message_counter(project_key, state_dir=common.DEFAULT_STATE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
