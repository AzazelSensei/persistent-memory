<p align="center"><img src="src/persistent_memory/daemon/static/pm/logo.png" width="140" alt="persistent-memory logo"></p>

# persistent-memory

**Local-first, reviewable memory and multi-model deliberation for AI coding agents.**

It stores selected engineering decisions and lessons as immutable Markdown, retrieves them with local embeddings, and makes them available to future agent sessions. Its optional **Council** uses several configured agent CLIs to deliberate on one decision over fixed rounds, then writes a human-reviewable proposed decision.

*Türkçe: [README.tr.md](README.tr.md)*

## What it is

- A decision-and-lesson store, not a chat-log archive or codebase RAG.
- Plain Markdown records in `docs/decisions/` and `docs/lessons/`, with provenance and supersession links rather than silent rewrites.
- A local daemon on `127.0.0.1:37778` that builds a local Ollama `bge-m3` vector index and injects bounded recall.
- A stdio MCP bridge to that local daemon, plus optional hooks and localhost HTTP.
- A machine-local service. Teams share reviewed records through Git; this is not a hosted public MCP service or a multi-tenant server.

## Local-first does not mean zero egress

Records, the vector index, and the daemon remain local. The system can also invoke authenticated hosted agent CLIs for extraction, recall-aware work, or Council deliberation. Those calls may send transcript-derived content, the Council topic, board messages, and recalled records to the configured provider. Their subscriptions, quotas, rate limits, retention, and privacy terms apply. Review the content you allow into a transcript or Council before enabling those workflows.

## How it works

```
Hooks / MCP  →  local daemon  →  Markdown records + local vector index
                    │                         │
                    ├── bounded recall  ←──────┘
                    └── optional Council → proposed decision
```

- **Capture:** hooks signal the daemon, which slices a transcript and invokes its matching configured CLI extraction backend. If that backend is unavailable, capture is skipped; existing records remain searchable and recallable.
- **Recall:** hybrid keyword, vector, recency, and salience retrieval produces a compact memory block within a fixed budget.
- **Council:** configured members receive the topic, relevant recall, and the append-only board. Round one runs independently in parallel; later rounds run in sequence so members can challenge the board. A spokesperson synthesizes a `proposed` decision record for human acceptance or rejection.

Council is for consequential questions where independent perspectives help: architecture, trade-offs, or product direction. It is a poor fit for routine edits or questions with one readily verifiable answer. It can finish with failed or skipped members and does not guarantee a correct consensus.

## MCP and Council

`persistent_memory.mcp_server` is a **stdio** MCP server. It talks only to the local daemon by default; it does not expose a hosted endpoint. It supports recall queries (`search_memory`, `get_record`, `list_recent`, `get_record_provenance`), a local authenticated `create_record`, and Council tools (`council_post`, `council_read`, `council_threads`, `council_open`, `council_status`).

Open a Council from an MCP-capable client, then poll its status:

```text
council_open(
  project="my-project",
  topic="Should the API use cursor pagination for the new activity feed?",
  cwd="/absolute/path/to/my-project",
  rounds=2
)

council_status(project="my-project", session_id="<returned-session-id>")
```

Only one Council session can be active per project. The runner records each member's outcome and writes the final synthesis as a proposed record only when it can produce one. Council members themselves are prevented from posting or creating records through this MCP server; their responses are captured by the runner.

The `project` argument scopes the Council board and session, **not** the Council's initial memory lookup. That lookup uses global memory search and can return record IDs, titles, and project names from other projects. A hosted Council CLI can receive those results along with the topic; do not use Council across a corpus whose cross-project metadata must stay isolated.

Add `.pm-council.yaml` to a project root when the defaults do not suit the project. This is a minimal valid configuration:

```yaml
version: 1
spokesperson: claude
rounds: 2
turn_timeout_seconds: 600
members:
  - id: claude
    backend: claude
    role: "System design and long-term trade-offs."
  - id: codex
    backend: codex
    role: "Implementation reality and measurable cost."
  - id: grok
    backend: grok
    role: "Challenge assumptions and surface alternatives."
```

Supported backends are `claude`, `codex`, `kimi`, and `grok`. Configured members and rounds are bounded (at most six members, five rounds, and 24 total turn calls including synthesis); disabled or unavailable members are reported in the session status.

## Requirements

- macOS for the supported installer and its launchd daemon registration.
- Python 3.12 or newer.
- Local [Ollama](https://ollama.com) with `bge-m3` for embeddings and recall.
- A matching authenticated agent CLI for automatic extraction. Council also needs each configured member CLI to be installed and authenticated.

## Quickstart

```bash
git clone https://github.com/AzazelSensei/persistent-memory.git
cd persistent-memory
./install.sh
```

Try the demo corpus after the daemon is available:

```bash
mkdir -p docs
cp -r examples/demo-corpus/decisions examples/demo-corpus/lessons docs/
curl 'http://127.0.0.1:37778/api/search?q=stale+cache+flash+sale'
open http://127.0.0.1:37778
```

The dashboard and HTTP API bind to `127.0.0.1:37778`. Installing registers the stdio MCP process with supported local CLIs when available; the MCP server still requires the local daemon to answer requests.

## Validation and retrieval evaluation

```bash
./.venv/bin/python -m persistent_memory.doctor --check
./.venv/bin/python -m pytest -q
cp eval/recall_queries.example.json eval/recall_queries.json
./.venv/bin/python eval/recall_eval.py
PM_EVAL_LIVE=1 ./.venv/bin/python -m pytest tests/test_recall_eval_gate.py -q
```

The public repository ships only the starter query set. Keep the populated `eval/recall_queries.json` local and tailor it to your corpus; the live evaluation commands require a running local model and records.

## Security boundaries

- The daemon binds to localhost and mutation endpoints use a local token.
- Extraction paths are checked against configured roots, and extraction treats transcript content as data rather than instructions.
- Council subprocesses are deliberately launched with provider-specific non-sandbox/bypass approval modes. `PM_COUNCIL_READONLY=1` blocks only this MCP server's `create_record` and `council_post` calls for Council members; it is not OS sandboxing or a general read-only guarantee.
- These controls are implementation boundaries, not a claim of production-grade isolation. Hosted CLI calls have the provider boundary described above.

## Developing

Read [AGENTS.md](AGENTS.md) before changing the code. It maps the architecture and its contracts, including record immutability, Council configuration, and the local MCP boundary.

## License

GNU Affero General Public License v3.0 or later — see [LICENSE](LICENSE). If you modify this software and run it as a network service, you must make the corresponding source available to its users under the AGPL.
