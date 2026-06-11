#!/usr/bin/env bash
# Manage the persistent-memory daemon as a macOS LaunchAgent.
# Usage: launchd.sh {install|load|unload|status}
set -euo pipefail

LABEL="com.persistent-memory.daemon"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_DIR}/.venv/bin/python"

usage() { echo "usage: $0 {install|load|unload|status}"; exit 1; }

install_plist() {
  "${PYTHON_BIN}" - "$PYTHON_BIN" "$REPO_DIR" "$PLIST" <<'PY'
import sys
from persistent_memory.daemon.launch_agent import build_launch_agent_plist
python_bin, working_dir, plist_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(plist_path, "w", encoding="utf-8") as fh:
    fh.write(build_launch_agent_plist(python_bin=python_bin, working_dir=working_dir))
print(f"wrote: {plist_path}")
PY
}

case "${1:-}" in
  install) install_plist ;;
  load)    launchctl load -w "$PLIST" && echo "loaded" ;;
  unload)  launchctl unload -w "$PLIST" && echo "unloaded" ;;
  status)  launchctl list | grep "$LABEL" || echo "not running" ;;
  *)       usage ;;
esac
