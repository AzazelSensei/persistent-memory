"""PreCompact hook — flush pending extraction before context is compacted.

Thin signal layer: posts a single flush signal to the daemon's extract
endpoint and resets the message counter. Always exits 0.
"""

import os
import sys

from persistent_memory.hooks import common
from persistent_memory.hooks.common import (
    build_project_key,
    post_daemon_signal,
    project_name,
    read_hook_payload,
    reset_message_counter,
)

EXTRACT_ENDPOINT = "/api/extract"
COMPACT_REASON = "pre_compact"


def main() -> int:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or os.getcwd()
    project_key = build_project_key(cwd)
    post_daemon_signal(
        EXTRACT_ENDPOINT,
        {
            "project": project_name(cwd),
            "cwd": cwd,
            "session_id": payload.get("session_id"),
            "transcript_path": payload.get("transcript_path"),
            "flush": True,
            "reason": COMPACT_REASON,
        },
    )
    reset_message_counter(project_key, state_dir=common.DEFAULT_STATE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
