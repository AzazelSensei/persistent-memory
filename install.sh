#!/usr/bin/env bash
# persistent-memory installer.
#
# What it does, in order:
#   1. doctor preflight — scans the machine and auto-installs missing prerequisites
#   2. creates .venv (python3.12) and pip-installs the package with [daemon,mcp] extras
#   3. copies skill/SKILL.md into ~/.claude/skills/persistent-memory
#   4. merges the five hooks (UserPromptSubmit/Stop/PreCompact/SessionStart/PreToolUse) into
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
#   PM_SKIP_LAUNCHD=1, PM_SKIP_CODEX=1, PM_SKIP_MCP=1, PM_INSTALL_CODEX=1 (force Codex step),
#   PM_SKIP_KIMI=1, PM_INSTALL_KIMI=1 (force Kimi step).
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
KIMI_DIR="$TARGET_HOME/.kimi-code"
KIMI_CONFIG="$KIMI_DIR/config.toml"
KIMI_MCP="$KIMI_DIR/mcp.json"
KIMI_SKILL_DEST="$KIMI_DIR/skills/persistent-memory"

HOOK_EVENTS=("UserPromptSubmit" "Stop" "PreCompact" "SessionStart" "PreToolUse")

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
    plan "create .venv at $VENV_DIR and pip install -e .[daemon,mcp] tomli_w"
    return
  fi
  [[ "${PM_SKIP_VENV:-0}" == "1" ]] && return
  [[ -d "$VENV_DIR" ]] || python3.12 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install -e "$REPO_ROOT[daemon,mcp]" tomli_w
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
    --arg ptu "$(hook_command pre_tool_use)" \
    'def upsert(cmd): map(select((.hooks[0].command // "") != cmd)) + [{"hooks":[{"type":"command","command":cmd}]}];
     def upsert_matcher(cmd; matcher; tout): map(select((.hooks[0].command // "") != cmd)) + [{"matcher":matcher,"hooks":[{"type":"command","command":cmd,"timeout":tout}]}];
     .hooks = (.hooks // {})
     | .hooks.UserPromptSubmit = ((.hooks.UserPromptSubmit // []) | upsert($ups))
     | .hooks.Stop = ((.hooks.Stop // []) | upsert($stop))
     | .hooks.PreCompact = ((.hooks.PreCompact // []) | upsert($pre))
     | .hooks.SessionStart = ((.hooks.SessionStart // []) | upsert($ss))
     | .hooks.PreToolUse = ((.hooks.PreToolUse // []) | upsert_matcher($ptu; "Agent|Task"; 5))' \
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

should_install_kimi() {
  [[ "${PM_SKIP_KIMI:-0}" == "1" ]] && return 1
  [[ "${PM_INSTALL_KIMI:-0}" == "1" ]] && return 0
  command -v kimi >/dev/null 2>&1 && return 0
  [[ -d "$KIMI_DIR" ]] && return 0
  return 1
}

install_kimi_skill() {
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "copy $REPO_ROOT/skill/SKILL.md to $KIMI_SKILL_DEST/SKILL.md (.kimi-code/skills/persistent-memory)"
    return
  fi
  mkdir -p "$KIMI_SKILL_DEST"
  cp "$REPO_ROOT/skill/SKILL.md" "$KIMI_SKILL_DEST/SKILL.md"
}

register_kimi_hooks() {
  if [[ $DRY_RUN -eq 1 ]]; then
    for event in "${HOOK_EVENTS[@]}"; do
      plan "merge kimi hook $event into $KIMI_CONFIG"
    done
    return
  fi
  mkdir -p "$KIMI_DIR"
  "$VENV_DIR/bin/python" - "$KIMI_CONFIG" "$VENV_DIR" <<'PYEOF'
import json
import os
import sys

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib

import tomli_w

config_path = sys.argv[1]
venv = sys.argv[2]

ours = [
    {"event": "UserPromptSubmit", "command": f"{venv}/bin/python -m persistent_memory.hooks.user_prompt_submit"},
    {"event": "Stop", "command": f"{venv}/bin/python -m persistent_memory.hooks.stop_or_session_end"},
    {"event": "PreCompact", "command": f"{venv}/bin/python -m persistent_memory.hooks.pre_compact"},
    {"event": "SessionStart", "command": f"{venv}/bin/python -m persistent_memory.hooks.session_start"},
    {"event": "PreToolUse", "matcher": "Agent|Task", "command": f"{venv}/bin/python -m persistent_memory.hooks.pre_tool_use", "timeout": 5},
]
our_cmds = {h["command"] for h in ours}

try:
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
except FileNotFoundError:
    data = {}

hooks = [h for h in data.get("hooks", []) if not (isinstance(h, dict) and h.get("command") in our_cmds)]
hooks.extend(ours)
data["hooks"] = hooks

with open(config_path, "wb") as f:
    tomli_w.dump(data, f)
PYEOF
  say "Kimi hooks written to $KIMI_CONFIG"
}

register_kimi_mcp() {
  [[ "${PM_SKIP_MCP:-0}" == "1" ]] && return
  local cmd="$VENV_DIR/bin/python"
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "register MCP server 'persistent-memory' ($cmd -m persistent_memory.mcp_server) in $KIMI_MCP"
    return
  fi
  mkdir -p "$KIMI_DIR"
  "$VENV_DIR/bin/python" - "$KIMI_MCP" "$cmd" <<'PYEOF'
import json
import os
import sys

mcp_path = sys.argv[1]
cmd = sys.argv[2]

try:
    with open(mcp_path, "r", encoding="utf-8") as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {}

servers = data.setdefault("mcpServers", {})
servers["persistent-memory"] = {
    "command": cmd,
    "args": ["-m", "persistent_memory.mcp_server"],
}

with open(mcp_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF
  say "Kimi MCP 'persistent-memory' registered in $KIMI_MCP"
}

_lang_subtag() {
  echo "$1" | sed 's/[._@-].*//' | tr '[:upper:]' '[:lower:]'
}

detect_lang() {
  local lang=""
  for var in PM_LANG LC_ALL LANG; do
    local val="${!var:-}"
    if [[ -n "$val" ]]; then
      lang="$(_lang_subtag "$val")"
      if [[ -n "$lang" ]]; then
        echo "$lang"
        return
      fi
    fi
  done
  local apple
  apple="$(defaults read -g AppleLocale 2>/dev/null || true)"
  if [[ -n "$apple" ]]; then
    lang="$(_lang_subtag "$apple")"
    [[ -n "$lang" ]] && echo "$lang" && return
  fi
  echo "en"
}

install_launchd() {
  local install_lang
  install_lang="$(detect_lang)"
  if [[ $DRY_RUN -eq 1 ]]; then
    plan "write LaunchAgents plist $PLIST_DEST with PM_LANG=$install_lang and launchctl load"
    return
  fi
  [[ "${PM_SKIP_LAUNCHD:-0}" == "1" ]] && return
  mkdir -p "$LAUNCH_AGENTS_DIR"
  PYTHONPATH="$REPO_ROOT/src" "$VENV_DIR/bin/python" - "$VENV_DIR/bin/python" "$REPO_ROOT" "$install_lang" <<'PYEOF' > "$PLIST_DEST"
import sys
from persistent_memory.daemon.launch_agent import build_launch_agent_plist
python_bin, working_dir, lang = sys.argv[1], sys.argv[2], sys.argv[3]
print(build_launch_agent_plist(python_bin=python_bin, working_dir=working_dir, lang=lang if lang else None), end="")
PYEOF
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
if should_install_kimi; then
  install_kimi_skill
  register_kimi_hooks
  register_kimi_mcp
fi
register_mcp
install_launchd
say "Done."
