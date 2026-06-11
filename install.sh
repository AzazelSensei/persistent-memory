#!/usr/bin/env bash
# persistent-memory installer.
#
# What it does, in order:
#   1. doctor preflight — scans the machine and auto-installs missing prerequisites
#   2. creates .venv (python3.12) and pip-installs the package with [daemon,mcp] extras
#   3. copies skill/SKILL.md into ~/.claude/skills/persistent-memory
#   4. merges the four hooks (UserPromptSubmit/Stop/PreCompact/SessionStart) into
#      ~/.claude/settings.json (idempotent; existing user hooks are preserved; needs jq)
#   5. if the `codex` CLI (or ~/.codex) is detected, mirrors hooks + skill into ~/.codex
#   6. registers the read-only MCP server with `claude mcp` / `codex mcp` when available
#   7. writes a macOS LaunchAgent plist and loads the daemon via launchctl
#
# Assumptions: macOS (launchd step), python3.12 and jq on PATH (doctor installs them),
# Claude Code and/or Codex CLI optional — missing tools are skipped with a message.
#
# Usage: ./install.sh [--dry-run]
# Env flags: PM_TARGET_HOME (target home dir), PM_SKIP_DOCTOR=1, PM_SKIP_VENV=1,
#   PM_SKIP_LAUNCHD=1, PM_SKIP_CODEX=1, PM_SKIP_MCP=1, PM_INSTALL_CODEX=1 (force Codex step).
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_HOME="${PM_TARGET_HOME:-$HOME}"
CLAUDE_DIR="$TARGET_HOME/.claude"
SKILL_DEST="$CLAUDE_DIR/skills/persistent-memory"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
LAUNCH_AGENTS_DIR="$TARGET_HOME/Library/LaunchAgents"
PLIST_DEST="$LAUNCH_AGENTS_DIR/com.persistent-memory.daemon.plist"
VENV_DIR="$REPO_ROOT/.venv"
CODEX_DIR="$TARGET_HOME/.codex"
CODEX_HOOKS_FILE="$CODEX_DIR/hooks.json"
CODEX_SKILL_DEST="$CODEX_DIR/skills/persistent-memory"

HOOK_EVENTS=("UserPromptSubmit" "Stop" "PreCompact" "SessionStart")

say() { echo "$@"; }
plan() { say "DRY-RUN: $*"; }

DOCTOR_MODULE="persistent_memory.doctor"

run_doctor() {
  [[ "${PM_SKIP_DOCTOR:-0}" == "1" ]] && return
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "preflight: PYTHONPATH=$REPO_ROOT/src python3 -m $DOCTOR_MODULE --dry-run"
    ( cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT/src" python3 -m "$DOCTOR_MODULE" --dry-run )
    return
  fi
  ( cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT/src" python3 -m "$DOCTOR_MODULE" )
}

create_venv() {
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "create .venv at $VENV_DIR and pip install -e .[daemon,mcp]"
    return
  fi
  [[ "${PM_SKIP_VENV:-0}" == "1" ]] && return
  [[ -d "$VENV_DIR" ]] || python3.12 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install -e "$REPO_ROOT[daemon,mcp]"
}

install_skill() {
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "copy $REPO_ROOT/skill/SKILL.md to $SKILL_DEST/SKILL.md (skills/persistent-memory)"
    return
  fi
  mkdir -p "$SKILL_DEST"
  cp "$REPO_ROOT/skill/SKILL.md" "$SKILL_DEST/SKILL.md"
}

hook_command() {
  echo "$VENV_DIR/bin/python -m persistent_memory.hooks.$1"
}

merge_hooks_into() {
  local file="$1"
  [[ -f "$file" ]] || echo '{}' > "$file"
  local tmp; tmp="$(mktemp)"
  jq \
    --arg ups "$(hook_command user_prompt_submit)" \
    --arg stop "$(hook_command stop_or_session_end)" \
    --arg pre "$(hook_command pre_compact)" \
    --arg ss "$(hook_command session_start)" \
    'def upsert(cmd): map(select((.hooks[0].command // "") != cmd)) + [{"hooks":[{"type":"command","command":cmd}]}];
     .hooks = (.hooks // {})
     | .hooks.UserPromptSubmit = ((.hooks.UserPromptSubmit // []) | upsert($ups))
     | .hooks.Stop = ((.hooks.Stop // []) | upsert($stop))
     | .hooks.PreCompact = ((.hooks.PreCompact // []) | upsert($pre))
     | .hooks.SessionStart = ((.hooks.SessionStart // []) | upsert($ss))' \
    "$file" > "$tmp"
  mv "$tmp" "$file"
}

register_hooks() {
  if [[ $DRY_RUN -eq 1 ]]; then
    for event in "${HOOK_EVENTS[@]}"; do
      plan "merge hook $event into settings.json (Claude Code)"
    done
    return
  fi
  mkdir -p "$CLAUDE_DIR"
  merge_hooks_into "$SETTINGS_FILE"
}

register_codex_hooks() {
  [[ "${PM_SKIP_CODEX:-0}" == "1" ]] && return
  if ! command -v codex >/dev/null 2>&1 && [[ ! -d "$CODEX_DIR" && "${PM_INSTALL_CODEX:-0}" != "1" ]]; then
    say "codex not found — skipping Codex hooks (force with PM_INSTALL_CODEX=1)"
    return
  fi
  if [[ $DRY_RUN -eq 1 ]]; then
    for event in "${HOOK_EVENTS[@]}"; do
      plan "merge codex hook $event into $CODEX_HOOKS_FILE"
    done
    plan "copy $REPO_ROOT/skill/SKILL.md to $CODEX_SKILL_DEST/SKILL.md (.codex/skills/persistent-memory)"
    return
  fi
  mkdir -p "$CODEX_DIR"
  merge_hooks_into "$CODEX_HOOKS_FILE"
  mkdir -p "$CODEX_SKILL_DEST"
  cp "$REPO_ROOT/skill/SKILL.md" "$CODEX_SKILL_DEST/SKILL.md"
  say "Codex hooks written to $CODEX_HOOKS_FILE — trust them via '/hooks' in Codex (or --dangerously-bypass-hook-trust)."
}

register_mcp() {
  [[ "${PM_SKIP_MCP:-0}" == "1" ]] && return
  local name="persistent-memory"
  local cmd="$VENV_DIR/bin/python"
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "register MCP server '$name' ($cmd -m persistent_memory.mcp_server) in Claude + Codex"
    return
  fi
  if command -v claude >/dev/null 2>&1; then
    claude mcp remove -s user "$name" >/dev/null 2>&1 || true
    if claude mcp add -s user "$name" -- "$cmd" -m persistent_memory.mcp_server >/dev/null 2>&1; then
      say "Claude MCP '$name' registered (scope user)."
    else
      say "Claude MCP registration failed — run manually: claude mcp add -s user $name -- $cmd -m persistent_memory.mcp_server"
    fi
  fi
  if command -v codex >/dev/null 2>&1; then
    codex mcp remove "$name" >/dev/null 2>&1 || true
    if codex mcp add "$name" -- "$cmd" -m persistent_memory.mcp_server >/dev/null 2>&1; then
      say "Codex MCP '$name' registered."
    else
      say "Codex MCP registration failed — run manually: codex mcp add $name -- $cmd -m persistent_memory.mcp_server"
    fi
  fi
}

install_launchd() {
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "write LaunchAgents plist $PLIST_DEST and launchctl load"
    return
  fi
  [[ "${PM_SKIP_LAUNCHD:-0}" == "1" ]] && return
  mkdir -p "$LAUNCH_AGENTS_DIR"
  cat > "$PLIST_DEST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.persistent-memory.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_DIR/bin/python</string>
    <string>-m</string>
    <string>persistent_memory.daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>$REPO_ROOT</string>
  <key>StandardOutPath</key><string>/tmp/persistent-memory-daemon.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/persistent-memory-daemon.err.log</string>
</dict>
</plist>
PLIST
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
  launchctl bootout "gui/$(id -u)/com.persistent-memory.daemon" 2>/dev/null || true
  launchctl remove com.persistent-memory.daemon 2>/dev/null || true
  launchctl load "$PLIST_DEST"
}

say "persistent-memory install (dry_run=$DRY_RUN)"
run_doctor
create_venv
install_skill
register_hooks
register_codex_hooks
register_mcp
install_launchd
say "Done."
