"""Read-only ingest of claude-mem observations into the unified corpus.

Opens the claude-mem SQLite database strictly read-only (mode=ro +
PRAGMA query_only), exports observations as frontmattered markdown with a
dedup ledger, and assembles the unified corpus directory as symlinks to the
decision/lesson/observation sources — the corpus never owns or copies records.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import frontmatter

RO_URI_TEMPLATE = "file:{path}?mode=ro&immutable=1"
RO_URI_LIVE_TEMPLATE = "file:{path}?mode=ro"
CLAUDEMEM_DB_PATH = Path.home() / ".claude-mem" / "claude-mem.db"


class ClaudeMemDbError(Exception):
    pass


def open_claudemem_db(db_path: str, is_immutable: bool = False) -> sqlite3.Connection:
    if not os.path.isfile(db_path):
        raise ClaudeMemDbError(f"claude-mem db not found: {db_path}")
    template = RO_URI_TEMPLATE if is_immutable else RO_URI_LIVE_TEMPLATE
    uri = template.format(path=db_path)
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


OBSERVATION_COLUMNS = (
    "id", "memory_session_id", "project", "text", "type", "title", "subtitle",
    "facts", "narrative", "concepts", "files_read", "files_modified",
    "prompt_number", "created_at", "created_at_epoch", "content_hash",
)


def pull_observations(db_path: str, project: str, since_epoch: int = 0) -> list[sqlite3.Row]:
    if not project:
        raise ClaudeMemDbError("project filter is required for pull_observations")
    conn = open_claudemem_db(db_path)
    try:
        cols = ", ".join(OBSERVATION_COLUMNS)
        query = (
            f"SELECT {cols} FROM observations "
            "WHERE project = ? AND created_at_epoch >= ? "
            "ORDER BY created_at_epoch ASC, id ASC"
        )
        return conn.execute(query, (project, since_epoch)).fetchall()
    finally:
        conn.close()


SOURCE_NAME = "claude-mem"
OBSERVATION_TYPE = "observation"


def _parse_json_list(raw: object, field: str) -> list[str]:
    if raw is None or raw == "":
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ClaudeMemDbError(f"invalid JSON in field '{field}': {exc}") from exc
    if not isinstance(parsed, list):
        return [str(parsed)]
    return [str(item) for item in parsed]


def _build_observation_body(row: sqlite3.Row) -> str:
    facts = _parse_json_list(row["facts"], "facts")
    concepts = _parse_json_list(row["concepts"], "concepts")
    parts: list[str] = []
    title = row["title"]
    if title:
        parts.append(f"# {title}")
    narrative = row["narrative"]
    if narrative:
        parts.append(narrative)
    text = row["text"]
    if text:
        parts.append(text)
    if facts:
        parts.append("## Facts\n" + "\n".join(f"- {fact}" for fact in facts))
    if concepts:
        parts.append("## Concepts\n" + ", ".join(concepts))
    return "\n\n".join(parts)


def export_observation_to_md(row: sqlite3.Row, out_dir: str) -> str | None:
    obs_id = row["id"]
    body = _build_observation_body(row)
    if not body.strip():
        return None
    post = frontmatter.Post(body)
    post["type"] = OBSERVATION_TYPE
    post["source"] = SOURCE_NAME
    post["source_id"] = obs_id
    post["session"] = row["memory_session_id"]
    post["project"] = row["project"]
    post["created_at"] = row["created_at"]
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = out_path / f"obs-{obs_id}.md"
    file_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return str(file_path)


def export_observations(db_path: str, project: str, out_dir: str,
                        ledger_path: str, since_epoch: int = 0) -> list[str]:
    rows = pull_observations(db_path, project=project, since_epoch=since_epoch)
    ledger = DedupLedger(ledger_path)
    written: list[str] = []
    for row in rows:
        obs_id = row["id"]
        if ledger.is_exported(obs_id):
            continue
        path = export_observation_to_md(row, out_dir)
        if path is None:
            continue
        ledger.mark_exported(obs_id)
        written.append(path)
    ledger.save()
    return written


LEDGER_KEY = "exported_ids"


class DedupLedger:
    def __init__(self, ledger_path: str):
        self._path = Path(ledger_path)
        self._ids: set[int] = self._load()

    def _load(self) -> set[int]:
        if not self._path.is_file():
            return set()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ClaudeMemDbError(f"corrupt dedup ledger {self._path}: {exc}") from exc
        return set(data.get(LEDGER_KEY, []))

    def is_exported(self, obs_id: int) -> bool:
        return obs_id in self._ids

    def mark_exported(self, obs_id: int) -> None:
        self._ids.add(obs_id)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {LEDGER_KEY: sorted(self._ids)}
        self._path.write_text(json.dumps(payload), encoding="utf-8")


USER_PROMPT_COLUMNS = (
    "up.id", "up.content_session_id", "up.prompt_number", "up.prompt_text",
    "up.created_at", "up.created_at_epoch", "s.project",
)


def pull_user_prompts(db_path: str, project: str, since_epoch: int = 0) -> list[sqlite3.Row]:
    if not project:
        raise ClaudeMemDbError("project filter is required for pull_user_prompts")
    conn = open_claudemem_db(db_path)
    try:
        cols = ", ".join(USER_PROMPT_COLUMNS)
        query = (
            f"SELECT {cols} FROM user_prompts up "
            "JOIN sdk_sessions s ON s.content_session_id = up.content_session_id "
            "WHERE s.project = ? AND up.created_at_epoch >= ? "
            "ORDER BY up.created_at_epoch ASC, up.id ASC"
        )
        return conn.execute(query, (project, since_epoch)).fetchall()
    finally:
        conn.close()


MD_GLOB = "*.md"


def _collect_md_files(source_dir: str) -> list[Path]:
    path = Path(source_dir)
    if not path.is_dir():
        return []
    return sorted(path.glob(MD_GLOB))


def _clear_corpus_links(corpus_root: Path) -> None:
    if not corpus_root.is_dir():
        return
    for entry in corpus_root.iterdir():
        if entry.is_symlink():
            entry.unlink()


def build_unified_corpus(corpus_root: str, decisions_dir: str,
                         lessons_dir: str, observations_dir: str) -> list[Path]:
    root = Path(corpus_root)
    root.mkdir(parents=True, exist_ok=True)
    _clear_corpus_links(root)
    sources = (decisions_dir, lessons_dir, observations_dir)
    linked: list[Path] = []
    for source_dir in sources:
        for md_file in _collect_md_files(source_dir):
            link_path = root / md_file.name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(md_file.resolve())
            linked.append(link_path)
    return linked
