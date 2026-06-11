---
name: persistent-memory
description: Use when Claude Code needs a memory layer that AUTOMATICALLY remembers decisions/lessons; every 5 messages it extracts decisions (what/why) and mistakes/learnings from the conversation, merges three memories (claude-mem + graphify + persistent), searches with local embeddings, and injects a fixed-budget recall block at the start of the next session. Fully local, no extra API key.
trigger: persistent-memory
---

# persistent-memory

This skill runs AUTOMATICALLY in the background: every 5 messages, decisions (what/why) and mistakes/learnings (what/why/when noticed) are extracted from the accumulated conversation, embedded with local Ollama bge-m3, and at session start the relevant records are injected into context as a fixed ~1200-token recall block. Extraction is source-specific: Codex transcripts are processed by `codex exec --ignore-user-config -m gpt-5.3-codex-spark` with low reasoning effort, while Claude/manual extraction uses `claude -p --model claude-sonnet-4-6 --effort low`. Everything runs LOCALLY; no extra API key is required beyond the user's existing CLI subscription auth. The hook contract is identical in Claude Code and Codex.

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
   - Write endpoints (`/api/extract`, accept/reject, `/api/consolidate`) require the `X-PM-Token` header. The token file lives in the MEMORY repo (the daemon's records root), NOT in the project you are currently working in — discover it via `GET /api/health` (`records_dir` field): `<records_dir>/.pm-index/daemon.token`.

Notes: (a) The slash commands below are Claude Code-specific; on other agents use the HTTP endpoint or direct file write described in the "Writing records" section below. (b) Extraction uses per-source backends: Codex transcripts (`~/.codex/...`) are processed by `codex exec --ignore-user-config -m gpt-5.3-codex-spark -c model_reasoning_effort="low"`; Claude transcripts and manual `/api/extract` calls use `claude -p`. `PM_CODEX_BIN`, `PM_CODEX_EXTRACTION_MODEL` and `PM_CODEX_EXTRACTION_EFFORT` can override the Codex defaults; otherwise the macOS Codex.app CLI is preferred over `codex` from PATH when present. Without the relevant CLI, automatic record creation falls back gracefully (codex→claude if `codex` is missing; both CLIs absent → recall/search keep working in degraded mode, only auto-write is disabled). (c) Records are plain markdown (`docs/decisions/*.md`, `docs/lessons/*.md`); worst case, any agent can read the files directly.

## Writing records (any agent)

### 1. Primary: automatic extraction

Most records are created automatically via the extraction worker every 5 messages. The HTTP and file-write paths below are for "record this NOW" moments when you need to capture something immediately without waiting for the next extraction cycle.

### 2. HTTP (any agent)

The `POST /api/records` endpoint creates a record on demand. It requires the `X-PM-Token` header.

```bash
RECORDS_DIR=$(curl -s http://127.0.0.1:37778/api/health | python3 -c "import sys,json; print(json.load(sys.stdin)['records_dir'])")
TOKEN=$(cat "$RECORDS_DIR/.pm-index/daemon.token")
curl -X POST http://127.0.0.1:37778/api/records \
  -H "X-PM-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "lesson",
    "title": "Always validate input before parsing",
    "body": "## What happened\n\nParsing crashed on empty string.\n\n## General rule\n\nValidate before parse.",
    "project": "my-project",
    "tags": ["validation", "parsing"],
    "salience": 0.8,
    "session": "optional-session-id",
    "cwd": "/optional/working/dir",
    "agent": "codex"
  }'
```

Request fields: `type` (`"decision"` or `"lesson"`, required), `title` (required), `project` (required), `body` (optional — omit to use the canonical template), `tags` (optional list), `salience` (optional float 0–1, default 0.5), `session`/`cwd`/`agent` (optional provenance fields, defaults: `"manual"`/`""`/`"api"`).

Response on success (201): `{"id": "D-0001", "path": "/abs/path/to/file.md", "type": "decision"}`.

Other write operations (same token):
- Accept a candidate: `POST /api/records/{id}/accept`
- Reject a candidate: `POST /api/records/{id}/reject`
- Accept all proposed: `POST /api/records/accept-all?project=NAME&type=decision`
- Link supersession: `POST /api/records/{old_id}/supersede-by/{new_id}`
- Replace body (proposed only): `POST /api/records/{id}/body` with `{"body": "..."}`
- Dismiss supersession candidate: `POST /api/supersession-candidates/dismiss`

### 3. Direct file write (file-access agents)

Records are plain markdown. An agent with file-system access may create `docs/decisions/D-XXXX.md` or `docs/lessons/L-XXXX.md` directly:

1. **Pick the next free ID**: scan the directory for existing files matching `D-\d{4}.md` (or `L-\d{4}.md`), take the highest number, add 1, zero-pad to 4 digits (e.g. `D-0042`).
2. **Write frontmatter** (YAML between `---` delimiters):
   ```yaml
   id: D-0042
   type: decision        # or: lesson
   status: proposed
   date: '2026-06-11'
   project: my-project
   provenance:
     session: my-session-id
     cwd: /path/to/project
     agent: codex
   tags: []
   supersedes: []
   superseded-by: []
   salience: 0.5
   ```
3. **Write body** with the canonical section headings:
   - **Decision**: `## Context / Problem`, `## Decision`, `## Rationale`, `## Outcome / Learned`, `## Source (transcript)`
   - **Lesson**: `## What happened`, `## Why`, `## When discovered`, `## General rule`, `## Source (transcript)`
4. **Validate**: `./.venv/bin/python -m persistent_memory.lint docs` — must pass before considering the record complete.
5. The file watcher auto-embeds new files; no extra action needed.

## Manual commands (override)

For manual intervention outside the automatic flow:

- `/decision` — Record the decision being made right now (status=proposed). Context, driving factors, options, decision and rationale are asked for/extracted.
- `/lesson` — Record a mistake or learning immediately (what happened, why, when it was noticed, general rule).
- `/recall` — Fetch and show the recall block for the current project now.
- `/consolidate` — Trigger graphify consolidation (cluster-only or headless build), producing the surprises/questions analysis.

If no command is given you don't need to do anything; the system learns on its own.

## Language

Set `PM_LANG=tr` (or `PM_LANG=en`) to choose the display language for recall headers, dashboard UI chrome, and hook messages. Resolution order: `PM_LANG` → `LC_ALL` → `LANG` → macOS `AppleLocale` → `en`. Locale strings are normalised to their primary subtag (`tr_TR.UTF-8` → `tr`); unsupported values fall back to English. Supported: `en`, `tr`.

Record section headings (`## Context / Problem`, `## What happened`, etc.) stay canonical English by design — they are parsed by the extraction worker and must not vary.

`install.sh` detects the language at install time using the same resolution order and writes `PM_LANG` into the LaunchAgent plist's `EnvironmentVariables` block so the daemon starts with the correct locale on every macOS login.

## Doctor (prerequisite check)

When `install.sh` runs, doctor runs automatically as the first step: it scans the machine and FULL-AUTO installs missing prerequisites (in dependency order). You can rerun it any time:

- `/persistent-memory doctor` or `python -m persistent_memory.doctor` — scan + auto-install what's missing (default, full-auto).
- `python -m persistent_memory.doctor --check` — scan and report only, install nothing.
- `python -m persistent_memory.doctor --dry-run` — print the commands that would run, execute none.

Managed prerequisites: homebrew (manual), jq, python3.12, .venv + package, ollama, ollama service (:11434), bge-m3 model, graphify (python3.12), claude CLI (manual), claude-mem (manual), git (manual). Items marked `manual` are never auto-installed; they are reported with instructions. The SessionStart hook only detects CRITICAL gaps (ollama service/bge-m3/.venv) and adds a one-line warning — it does not install anything.
