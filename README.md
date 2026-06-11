<p align="center"><img src="src/persistent_memory/daemon/static/pm/logo.png" width="140" alt="persistent-memory logo"></p>

# persistent-memory

**Human-like persistent memory for AI coding agents — fully local, no extra API keys.**

You just code and talk. The system automatically extracts **decisions** (what was chosen and why) and **lessons** (what failed, why, and when) from your agent conversations, stores them as plain markdown in your repo, and reminds future sessions with a fixed-budget recall block. Mistakes are never deleted — they are superseded, with the original reasoning kept visible.

*Türkçe dokümantasyon: [README.tr.md](README.tr.md)*

## What it is — and what it isn't

**It is:**

- **A decision brain, not a chat log.** It captures *what you decided and why*, and *what failed and what rule you learned* — the two things teams actually lose between sessions, sprints and people.
- **An audit trail your agent can cite.** Every record carries provenance: which session, which working directory, which agent, with a quote from the original transcript.
- **Memory that admits mistakes.** Wrong decisions are never silently rewritten — they are superseded by a new record with an explicit rationale, and the old reasoning stays readable. Your future self can see not just the current answer, but the path (and dead ends) that led there.
- **Infrastructure-free.** One localhost daemon, one local embedding model, markdown files in your repo. No accounts, no cloud, no API keys, no per-token bills.

**It is not:**

- ❌ A RAG over your codebase — it remembers *decisions about* the code, not the code itself.
- ❌ A generic "remember everything" chat memory — it deliberately extracts only decisions and lessons, because recall quality dies when everything is memorable.
- ❌ A hosted multi-user platform — the daemon serves one machine; teams share memory the same way they share code: through git.

## Why not just use a hosted memory platform or DIY vector RAG?

| | **persistent-memory** | Hosted memory platforms | DIY vector RAG |
|---|---|---|---|
| Where your data lives | Your repo + your machine | Someone else's cloud | Your infra (you build it) |
| What gets stored | Curated decisions & lessons with provenance | Embeddings/summaries of everything | Whatever you chunk |
| When you were wrong | Superseded, rationale preserved | Overwritten or duplicated | Stale chunks linger |
| Can a human review it? | Yes — plain markdown, PR-able | Rarely | Not really |
| Retrieval quality | Measured: eval gate with recall@k / MRR / nDCG floors in tests | Trust the vendor | You measure it (if you remember to) |
| Cost & keys | Zero — local Ollama + your existing agent CLI subscription/auth | Subscription + API keys | Embedding API bills |
| Works with which agents | Claude Code, Codex CLI, any MCP client, plain `curl` | SDK-dependent | Whatever you wire |

The honest trade-off: hosted platforms give you cross-device sync and multi-user dashboards out of the box. This project chooses the other side — your engineering decisions never leave your machine, and the memory itself is a reviewable artifact in your repo instead of an opaque database.

## Built for teams (via git, not another server)

Because records are plain markdown inside the repo:

- **Decision history travels with the code.** Clone the repo, and every "why is it built this way" answer comes along — readable by humans on GitHub and injectable into any teammate's agent sessions.
- **Memory goes through code review.** Records can ship in PRs; a teammate can challenge a decision record the same way they challenge code.
- **Onboarding compresses.** A new developer (or a brand-new AI session) reads the decision/lesson history instead of re-asking the team — and the recall hook does it automatically.
- **Lessons stop repeating.** "We tried that in January, it broke the orders table" surfaces *before* the second attempt, with a link to the original incident.
- **No agent lock-in.** One teammate on Claude Code, another on Codex, a third scripting with `curl` — same memory, three access paths.

## Principles

- **Decisions are questioned, mistakes are not erased** — records are immutable; corrections happen through supersession links, so the full reasoning history survives.
- **Fully local, zero egress** — embeddings come from a local Ollama model; nothing leaves your machine.
- **Quality over tokens** — recall is injected within a fixed token budget, scoped to the current project, with cross-project hits blended in only above a similarity threshold.
- **Plain markdown as the source of truth** — records live in `docs/decisions/` and `docs/lessons/` and can be committed to git, so a human (or any other agent) can read the project's decision history straight from GitHub.

## How it works

```
Hooks (signal)  →  Daemon (FastAPI, 127.0.0.1:37778)  →  Records (docs/decisions, docs/lessons)
                        │                                      │
                        │                              Vector index (Ollama bge-m3, numpy)
                        │                                      │
                        └── Recall injection  ←  Hybrid retrieval (BM25 + vector + recency + salience, RRF)
```

- **Capture:** lightweight hooks fire every N messages and at session end; a background daemon slices the new part of the transcript and dispatches the source-specific extraction worker. Claude/manual transcripts use `claude -p`; Codex transcripts use `codex exec --ignore-user-config -m gpt-5.3-codex-spark` with low reasoning effort. `PM_CODEX_BIN` can pin the Codex CLI; otherwise the macOS Codex.app binary is preferred over PATH when present.
- **Index:** records are embedded locally with Ollama `bge-m3` (1024-dim, strong Turkish/English bridge) into a numpy vector index with content-hash freshness.
- **Recall:** at session start and on every prompt, the daemon retrieves the most relevant records (hybrid BM25 + vector ranking fused with RRF, weighted by recency and salience) and injects a compact memory block.
- **Consolidate:** an optional graph pass clusters records into communities and proposes supersession candidates, reviewable in the dashboard.

## Three ways any agent can use it

1. **Hooks (automatic)** — Claude Code and Codex CLI share the same hook contract; `install.sh` registers both. Recall and extraction run by themselves.
2. **MCP (pull)** — a read-only MCP server exposes `search_memory`, `get_record`, `list_recent`, `get_record_provenance` for mid-task queries.
3. **Plain HTTP** — any agent or script can hit the localhost API:
   ```bash
   curl 'http://127.0.0.1:37778/api/search?q=cache+invalidation&top_k=5'
   curl 'http://127.0.0.1:37778/api/recall?project=my-project'
   ```
   Write endpoints require the `X-PM-Token` header (token file: `docs/.pm-index/daemon.token`).

## Requirements

- macOS (the daemon runs under launchd; the code itself is portable, but the installer is macOS-specific)
- Python ≥ 3.12
- [Ollama](https://ollama.com) with the `bge-m3` model (the preflight doctor installs missing prerequisites)
- Claude Code CLI and/or Codex CLI for automatic extraction, depending on which agent produced the transcript. Without a matching CLI, capture degrades gracefully but search/recall keep working.

## Quickstart

```bash
git clone https://github.com/AzazelSensei/persistent-memory.git
cd persistent-memory
./install.sh            # doctor preflight + venv + hooks + launchd daemon
```

Try it immediately with the demo corpus:

```bash
cp -r examples/demo-corpus/decisions examples/demo-corpus/lessons docs/
curl 'http://127.0.0.1:37778/api/search?q=stale+cache+flash+sale'
open http://127.0.0.1:37778        # dashboard
```

> **Dashboard address:** always `http://127.0.0.1:37778` — the port is **fixed** (37778) and the daemon binds to localhost only. Opening `http://127.0.0.1` without the port will not load anything.

Useful commands:

```bash
./.venv/bin/python -m pytest -q                      # test suite
./.venv/bin/python -m persistent_memory.doctor --check   # prerequisite scan
./.venv/bin/python -m persistent_memory.daemon       # run daemon manually
./.venv/bin/python eval/recall_eval.py               # retrieval quality benchmark
scripts/backup.sh docs my-snapshot.tar.gz            # snapshot records + index
```

## Measuring retrieval quality

`eval/recall_eval.py` measures recall@k, MRR, nDCG@10 and latency over a query set (`eval/recall_queries.json`, gitignored — start from `eval/recall_queries.example.json` and grow it from your own missed queries). A live regression gate (`PM_EVAL_LIVE=1 pytest tests/test_recall_eval_gate.py`) fails when retrieval quality drops below measured floors — run it before merging any retrieval change.

## Security model

- The daemon binds to `127.0.0.1` only; write endpoints require a token compared in constant time.
- Transcript and working-directory paths passed to the extraction worker are validated against allow-listed roots.
- The extraction prompt treats transcript content strictly as data — instructions inside transcripts are never executed.

## Developing with AI agents

This project was built almost entirely by AI agents working from instruction files, and it is meant to be extended the same way. [`AGENTS.md`](AGENTS.md) is the agent-facing manual: architecture map, verified commands, hard rules (TDD, eval gates, immutability contracts) and known gotchas. Point your agent at it before asking for changes.

## License

GNU Affero General Public License v3.0 or later — see [LICENSE](LICENSE).

This project is licensed under the AGPL-3.0-or-later. If you modify this software and run it as a network service, you must make the complete corresponding source code of your modified version available to the users of that service.
