---
name: persistent-memory
description: Use when any coding agent (Claude Code, Codex, Kimi, Grok) needs the local persistent-memory layer — search past decisions/lessons, record a decision/lesson now, or verify daemon/hooks. Automatically extracts decisions (what/why) and mistakes every ~5 messages, embeds with local Ollama bge-m3, and injects fixed-budget recall. Local records and embeddings; extraction and Council use the configured agent providers.
trigger: persistent-memory
---

# persistent-memory

This skill runs AUTOMATICALLY in the background: every 5 messages, decisions (what/why) and mistakes/learnings (what/why/when noticed) are extracted from the accumulated conversation, embedded with local Ollama bge-m3, and at session start the relevant records are injected into context as a fixed ~1200-token recall block. Extraction uses the CLI matching the transcript source. Records and embeddings are local; extraction and Council prompts, and memories recalled into hosted agent sessions, may be sent to the configured model provider. Existing CLI authentication is used, and provider quotas or charges still apply. Hooks are supported on Claude Code, Codex CLI, Kimi Code CLI, and Grok CLI.

Triggering, embedding and recall are managed by the daemon (`127.0.0.1:37778`). Hooks only send signals; the heavy work happens in the daemon, debounced. When the daemon is down, hooks pass silently without blocking the session.

Hooks inject memory automatically (PUSH) where the host supports context injection. You MUST also use memory ACTIVELY via MCP tools (PULL): mid-task, when you wonder "what did we decide about this before?", use `search_memory(query)`, `get_record(id)`, `list_recent()`, `get_record_provenance(id)`. For "record this now" moments, use `create_record(record_type, title, project, body, tags, salience, session, cwd, agent, branch)`.

## Grok CLI (xAI) — required PULL habits

On Grok, passive hook stdout may not inject context the same way Claude does. Treat MCP as the primary memory path:

1. Before non-trivial work (architecture, deploy, debug, first touch of a domain/entity), call `search_memory` (via MCP `persistent-memory__search_memory`).
2. If a side-channel recall file exists at `~/.grok/persistent-memory/last-recall.md`, read it once at the start of a task when relevant.
3. Use `create_record` with `agent="grok"` when the user wants something recorded immediately.
4. Transcripts live under `~/.grok/sessions/<url-encoded-cwd>/<session_id>/chat_history.jsonl` and are extracted by the daemon when hooks fire.

## Whatever agent is using this (Claude / Codex / Kimi / Grok / other AI)

The agent reading this skill may not be Claude Code — the system is agent-agnostic and can be used in three ways:

1. **Automatic flow (hooks)** — Claude / Codex / Kimi / Grok; `install.sh` writes hooks for each host. Recall injection and extraction triggering happen on their own when the host supports them; the agent should still PULL via MCP when unsure.
2. **Mid-task use (MCP, the recommended PULL path)** — the `persistent-memory` MCP server is registered with Claude, Codex, Kimi, and Grok; any MCP-capable agent can call `search_memory(query, top_k)`, `get_record(id)`, `list_recent(type, limit)`, `get_record_provenance(id)` directly, and can create an immediate proposed record with `create_record(record_type, title, project, body, tags, salience, session, cwd, agent, branch)`.
3. **Plain HTTP (agents or scripts without hooks/MCP)** — the daemon runs on localhost; read endpoints need no token:
   - `curl 'http://127.0.0.1:37778/api/search?q=QUERY&top_k=5'` — hybrid search
   - `curl 'http://127.0.0.1:37778/api/prompt-recall?q=QUERY&project=PROJECT'` — memory block to append to a prompt
   - `curl 'http://127.0.0.1:37778/api/recall?project=PROJECT'` — session-start recall block
   - `curl 'http://127.0.0.1:37778/api/records/D-0001/raw'` — record body
   - Mutation endpoints (`/api/records`, `/api/extract`, accept/reject, `/api/consolidate`) require the `X-PM-Token` header. The token file lives in the MEMORY repo (the daemon's records root), NOT in the project you are currently working in — discover it via `GET /api/health` (`records_dir` field): `<records_dir>/.pm-index/daemon.token`.

Notes: (a) The slash commands below are Claude Code-specific; on other agents use the HTTP endpoint or direct file write described in the "Writing records" section below. (b) Extraction is **host-pure** — each transcript source spawns its own CLI, no cross-host fallback: Claude (`~/.claude/...`) → `claude -p`; Codex (`~/.codex/...`) → `codex exec`; Kimi (`~/.kimi-code/...`) → `kimi -p`; Grok (`~/.grok/.../chat_history.jsonl`) → `grok -p --always-approve`. If that host's binary is missing, extraction is skipped (`backend-unavailable`); search/recall keep working. Env overrides: `PM_CODEX_EXTRACTION_MODEL`, `PM_KIMI_EXTRACTION_MODEL`, `PM_GROK_EXTRACTION_MODEL` / `PM_GROK_EXTRACTION_EFFORT`, `PM_GROK_BIN`. (c) Records are plain markdown (`docs/decisions/*.md`, `docs/lessons/*.md`); worst case, any agent can read the files directly.

## Writing records (any agent)

### 1. Primary: automatic extraction

Most records are created automatically via the extraction worker every 5 messages. The MCP, HTTP, and file-write paths below are for "record this NOW" moments when you need to capture something immediately without waiting for the next extraction cycle.

### 2. MCP (MCP-capable agents)

Use `create_record(record_type, title, project, body, tags, salience, session, cwd, agent, branch)`.

- `record_type`: `"decision"` or `"lesson"`
- `title`: required record title
- `project`: required project/category name
- `body`: optional markdown body using the canonical headings; omit to use the template
- `tags`, `salience`, `session`, `cwd`, `agent`, `branch`: optional metadata/provenance

The MCP tool discovers `records_dir` via `/api/health`, reads `<records_dir>/.pm-index/daemon.token`, and calls `POST /api/records`; it does not expose the token in its response.

### 3. HTTP (any agent)

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

### 4. Direct file write (file-access agents)

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

## AI Council (multi-agent deliberation)

A separate primitive layered on the same daemon: a shared, append-only project board (`docs/council/<project>/board.jsonl`) plus a guided deliberation mode where several AI CLIs (Claude, Codex, Grok — Kimi optional) debate one question over fixed rounds and a spokesperson synthesizes the outcome back into memory as a `proposed` D-record. Config: `.pm-council.yaml` in the project root.

### Posting/reading the board (any MCP-capable agent)

- `council_post(body, project, thread="general", kind="note", role=None, refs=None, author="agent")` — leave a note/question/critique/decision for whoever works on this project next, across sessions and hosts. Always pass your own identity as `author` (e.g. `"codex"`, `"grok"`) — the default `"agent"` is a placeholder, not an identity.
- `council_read(project, thread=None, since=None, limit=20)` — catch up on the board, or poll incrementally by passing `since` (an `m-####` cursor from your last read).
- `council_threads(project)` — see which threads exist and who is active before diving into one with `council_read`.

`thread="general"` is free-form chat; an active council session uses its own thread id (e.g. `"c-0007"`).

### Opening a council / watching it run

- `council_open(project, topic, cwd, rounds=None)` — starts a deliberation session. Only one active session runs per project at a time; opening a second one while another is pending/running returns the id of the existing session instead of starting a new one.
- `council_status(project, session_id=None)` — round-by-round member status (`done`/`failed`/`timeout`/`skipped`) and the resulting decision record id, if any. Poll this after `council_open` rather than guessing when a session finished.

### If you are running AS a council member

**Do not write to the board yourself, and do not call `create_record`.** The runner captures your answer and writes the board entry. Member subprocesses receive `PM_COUNCIL_READONLY=1`, which blocks this MCP server's `council_post` and `create_record` tools to avoid duplicate records. `council_read` and `search_memory` remain available.

Council initial recall searches across all projects in the memory store; its project parameter scopes the board and session, not the recalled corpus. IDs, titles, and project names from other projects may enter the provider prompt.

This flag is not an operating-system sandbox or a general read-only guarantee. Council currently launches Claude with `bypassPermissions`, Codex with `--dangerously-bypass-approvals-and-sandbox`, and Grok with `--always-approve`; their other tools can access the working environment. Run Council only in a trusted environment and review the selected project, members, and prompt before starting. This project exposes a local stdio MCP server and localhost HTTP API, not a hosted public MCP service.

### What the human does

The dashboard's Council tab has three sub-tabs: **Board** (free-form message stream, thread filter, post a note as a human), **Sessions** (start a session with a topic/round count/dry-run preview, watch it run turn-by-turn with live polling, cancel it, follow the link to the resulting decision record), **Prompt** (edit the global council prompt layer, see which line comes from code vs. `docs/council/prompt.md` vs. `.pm-council.yaml`, reset to default).

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
