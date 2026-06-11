---
name: persistent-memory
description: Use when Claude Code needs a memory layer that AUTOMATICALLY remembers decisions/lessons; every 5 messages it extracts decisions (what/why) and mistakes/learnings from the conversation, merges three memories (claude-mem + graphify + persistent), searches with local embeddings, and injects a fixed-budget recall block at the start of the next session. Fully local, no extra API key.
trigger: persistent-memory
---

# persistent-memory

This skill runs AUTOMATICALLY in the background: every 5 messages, decisions (what/why) and mistakes/learnings (what/why/when noticed) are extracted from the accumulated conversation, embedded with local Ollama bge-m3, and at session start the relevant records are injected into context as a fixed ~1200-token recall block. Since extraction is a mechanical task it runs on Sonnet 4.6 (~70% cheaper than Opus, equivalent quality — measured by benchmark). Everything runs LOCALLY; no extra API key is required (headless `claude -p` uses subscription auth). The hook contract is identical in Claude Code and Codex.

Triggering, embedding and recall are managed by the daemon (`127.0.0.1:37778`). Hooks only send signals; the heavy work happens in the daemon, debounced. When the daemon is down, hooks pass silently without blocking the session.

Hooks inject memory automatically (PUSH). You can also query memory ACTIVELY via the **read-only MCP tools** (PULL): mid-task, when you wonder "what did we decide about this before?", use `search_memory(query)`, `get_record(id)`, `list_recent()`, `get_record_provenance(id)`.

## Whatever agent is using this (Claude / Codex / other AI)

The agent reading this skill may not be Claude Code — the system is agent-agnostic and can be used in three ways:

1. **Automatic flow (hooks)** — the hook contract is identical in Claude Code and Codex CLI; `install.sh` writes hooks for both tools. Recall injection and extraction triggering happen on their own; the agent does not need to do anything.
2. **Mid-task query (MCP, the recommended PULL path)** — the `persistent-memory` MCP server is registered with both Claude and Codex; any MCP-capable agent can call `search_memory(query, top_k)`, `get_record(id)`, `list_recent(type, limit)`, `get_record_provenance(id)` directly.
3. **Plain HTTP (agents or scripts without hooks/MCP)** — the daemon runs on localhost; read endpoints need no token:
   - `curl 'http://127.0.0.1:37778/api/search?q=QUERY&top_k=5'` — hybrid search
   - `curl 'http://127.0.0.1:37778/api/prompt-recall?q=QUERY&project=PROJECT'` — memory block to append to a prompt
   - `curl 'http://127.0.0.1:37778/api/recall?project=PROJECT'` — session-start recall block
   - `curl 'http://127.0.0.1:37778/api/records/D-0001/raw'` — record body
   - Write endpoints (`/api/extract`, accept/reject, `/api/consolidate`) require the `X-PM-Token` header; token file: `docs/.pm-index/daemon.token` in the repo root.

Notes: (a) The slash commands below are Claude Code-specific; on other agents their equivalents are the MCP/HTTP calls above. (b) The extraction worker that WRITES records uses `claude -p` — without the `claude` CLI on the machine, automatic record creation will not run, but recall/search keep working (degraded mode). (c) Records are plain markdown (`docs/decisions/*.md`, `docs/lessons/*.md`); worst case, any agent can read the files directly.

## Manual commands (override)

For manual intervention outside the automatic flow:

- `/decision` — Record the decision being made right now (status=proposed). Context, driving factors, options, decision and rationale are asked for/extracted.
- `/lesson` — Record a mistake or learning immediately (what happened, why, when it was noticed, general rule).
- `/recall` — Fetch and show the recall block for the current project now.
- `/consolidate` — Trigger graphify consolidation (cluster-only or headless build), producing the surprises/questions analysis.

If no command is given you don't need to do anything; the system learns on its own.

## Doctor (prerequisite check)

When `install.sh` runs, doctor runs automatically as the first step: it scans the machine and FULL-AUTO installs missing prerequisites (in dependency order). You can rerun it any time:

- `/persistent-memory doctor` or `python -m persistent_memory.doctor` — scan + auto-install what's missing (default, full-auto).
- `python -m persistent_memory.doctor --check` — scan and report only, install nothing.
- `python -m persistent_memory.doctor --dry-run` — print the commands that would run, execute none.

Managed prerequisites: homebrew (manual), jq, python3.12, .venv + package, ollama, ollama service (:11434), bge-m3 model, graphify (python3.12), claude CLI (manual), claude-mem (manual), git (manual). Items marked `manual` are never auto-installed; they are reported with instructions. The SessionStart hook only detects CRITICAL gaps (ollama service/bge-m3/.venv) and adds a one-line warning — it does not install anything.
