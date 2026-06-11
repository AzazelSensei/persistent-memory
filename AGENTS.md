# AGENTS.md — manual for AI agents working on this codebase

This project is developed primarily by AI coding agents (Claude Code, Codex CLI, or similar). This file is the agent-facing contract: read it fully before changing code.

## What this is

A local-first persistent memory layer for AI coding agents. It extracts decisions/lessons from agent transcripts, stores them as immutable markdown records, embeds them with a local Ollama model, and injects budgeted recall into future sessions. See `README.md` for the user-facing overview.

## Architecture map

```
src/persistent_memory/
  schema.py            record model (pydantic): id, type, status, provenance, supersession, salience
  records.py           record CRUD: atomic writes, immutability rules, supersession linking
  index.py             markdown index generation for record directories
  lint.py              corpus validator (schema, duplicate ids, broken links, supersession symmetry)
  embeddings.py        Ollama bge-m3 client + numpy VectorIndex (content-hash freshness, atomic save)
  retriever.py         hybrid search: BM25 + vector + recency + salience, RRF fusion (CENTRAL FILE)
  query_expansion.py   synonym-based query expansion + Turkish-aware token folding
  recall.py            fixed-token-budget recall block builder
  transcripts.py       transcript discovery/slicing (watermark-based incremental extraction)
  transcript_rag.py    transcript chunk retrieval for source attribution
  extraction_prompt.py prompt for the headless extraction worker
  consolidate.py       graph-based consolidation: communities, supersession candidates
  graph_ingest.py      read-only ingest from external memory stores
  mcp_server.py        read-only MCP server (search/get/list/provenance)
  doctor.py            preflight prerequisite scanner/installer (stdlib-only by design)
  hooks/               thin hook entrypoints: signal the daemon, never do heavy work
  daemon/              FastAPI app, services, file watcher, launchd plist, dashboard (React JSX, no build step)
tests/                 pytest suite — mirrors module structure; daemon tests use TestClient
eval/                  retrieval quality benchmark (recall@k, MRR, nDCG@10, latency)
```

Data flow: hooks (signal) → daemon (heavy work) → records → vector index → retrieval → recall injection. Hooks must stay thin; anything slow belongs in the daemon.

## Verified commands

```bash
./.venv/bin/python -m pytest -q                  # full suite — must stay green
./.venv/bin/python -m pytest tests/daemon/ -q    # daemon subset
./.venv/bin/python -m persistent_memory.lint <records-dir>
./.venv/bin/python -m persistent_memory.daemon   # manual daemon run (127.0.0.1:37778)
./.venv/bin/python eval/recall_eval.py           # live benchmark (requires Ollama + a corpus)
PM_EVAL_LIVE=1 ./.venv/bin/python -m pytest tests/test_recall_eval_gate.py -q   # retrieval regression gate
```

Always use `./.venv/bin/python` — the system python may not have the dependencies.

## Hard rules

1. **TDD.** Failing test first, watch it fail, minimal code, watch it pass, full suite. No exceptions for "trivial" changes.
2. **The eval gate is law for retrieval changes.** Any change touching `retriever.py`, `embeddings.py`, `query_expansion.py`, or the search path in `daemon/services.py` must pass the live gate AND must not lower measured MRR. If quality drops: revert and report — do not commit, do not weaken thresholds.
3. **Records are immutable data contracts.** Never change the frontmatter schema, status values, or file format casually — records on users' disks must keep parsing. Corrections happen via supersession, never edits to accepted record bodies.
4. **Atomic writes everywhere.** Records and index files are written via temp-file + `os.replace`. Keep it that way; partial writes corrupt user memory.
5. **Scope discipline on central files.** `retriever.py` and `daemon/services.py` affect every retrieval path. Prefer the narrowest possible diff; do not refactor them opportunistically while fixing something else.
6. **No empty `except`.** Internal logic raises meaningful exceptions; boundary layers (hooks, daemon endpoints) may swallow but must log.
7. **Thread safety pattern.** Module-level caches use a dedicated `threading.Lock`: locked read → unlocked build → locked write. Leaf locks only — never acquire another lock while holding one.
8. **One commit per task,** message format `area: what was done` (past tense, ≤72 chars). Never `git add -A` — a live daemon may be generating records in `docs/` while you work.

## Deliberate design choices (do not "fix" these)

- **Min-max normalization of RRF scores is intentional.** Replacing it with a fixed scale was measured and REGRESSED recall@1 (compressed relevance lets the salience/recency mix flip near-ties). If you want absolute RRF confidence, you must rebalance the score weights in the same change and re-measure.
- **Score weights (relevance 0.90 / salience 0.07 / recency 0.03) were chosen by an 8-combo live sweep.** Don't tweak them without re-running the sweep.
- **BM25 cache signature is `(id, body_len, title_len, tags_len)` — an accepted approximation.** Same-length content changes won't refresh BM25; the vector path refreshes via content hash, and records are immutable in practice.
- **`DAMPENED_STATUSES` in retriever.py is live** (used by reverted-as-mistake records). Do not remove it as dead code.
- **The extraction worker prompt treats transcripts as data, never instructions** — keep the security preamble intact.
- **`doctor.py` is stdlib-only by design** — it runs before the venv exists. No third-party imports there.

## Known gotchas

- `schema.Record` has **no** `title`/`body` attributes; the retriever and embedder consume an `EmbedView` adapter (`adapt_loaded_record`). The title comes from `index._extract_title(body)`.
- Turkish casefold: `"GİRİŞ".casefold()` produces a combining-dot form that won't match `"giriş"`. All token matching must go through `_fold_token` (NFKD + casefold + combining-strip + ı→i).
- The daemon loads code at startup — code changes need a daemon restart to take effect (`launchctl kickstart -k gui/$UID/com.persistent-memory.daemon`).
- The file watcher handles `on_moved` because atomic writes are renames — creating records via temp+replace fires `on_moved`, not `on_modified`.
- Watermark-based transcript slicing resets when `watermark > total` (transcript compaction shrinks files).
- Tests gated behind `PM_E2E=1` and `PM_EVAL_LIVE=1` need live services (Ollama, a corpus) and are skipped in CI on purpose. An unexpected increase in skipped tests is a failure signal.

## How extraction works (for changes to the capture path)

1. A hook posts to `/api/extract` with the transcript path and project.
2. `prepare_extraction_input` validates the path against allow-listed roots, slices messages past the watermark, and writes a slice file.
3. A detached source-specific extraction process reads the slice and writes new records under `docs/decisions/` / `docs/lessons/` (and nothing else — enforced by the prompt's security preamble). Claude/manual transcripts use `claude -p --model claude-sonnet-4-6`; Codex transcripts use `codex exec --ignore-user-config -m gpt-5.3-codex-spark -c model_reasoning_effort="low"`. `PM_CODEX_BIN` can pin the Codex CLI; otherwise the macOS Codex.app binary is preferred over PATH when present.
4. The file watcher notices new records and embeds them; a 900s timeout kills hung workers.

Without the matching CLI installed, capture degrades gracefully: search/recall/MCP/HTTP keep working.

## Quality bar for contributions

- Full suite green (`pytest -q`), no reduction in passed count.
- Retrieval changes: live gate green + MRR not lowered (state the numbers in your report).
- New behavior needs tests that verify behavior, not mocks of it.
- Update this file when you change architecture, invariants, or commands.
