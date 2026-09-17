"""SSE endpoint for live record notifications: new decisions/lessons on disk.

`register_live_routes(app, cfg)` wires `GET /api/stream/records` onto an
existing FastAPI app, following `council/api.py`'s polling-SSE pattern but
kept in its own module so it stays independent of the council board/session
code. No token is required (read-only).

Detection is directory-listing based, never a full-corpus read: each poll
tick only stats `decisions/` and `lessons/` for an mtime change (new/removed
file), and only glob-lists filenames to compare id sequence numbers against
the last known watermark per prefix. Frontmatter is parsed only for the
handful of files that turned out to be new.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import yaml
from fastapi import Query
from fastapi.responses import StreamingResponse

from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.schema import ID_PATTERN

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15
MAX_STREAM_SECONDS = 3600

RECORD_INDEX_FILENAME = "index.md"
TYPE_BY_PREFIX = {"D": "decision", "L": "lesson", "P": "principle"}
H1_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _record_sequences(directory: Path) -> dict[str, int]:
    """Map record id -> sequence number for every record file in `directory`.

    Filename-only listing (no file content read) so this is cheap to call on
    every poll tick.
    """
    sequences: dict[str, int] = {}
    if not directory.is_dir():
        return sequences
    for path in directory.glob("*.md"):
        if path.name == RECORD_INDEX_FILENAME:
            continue
        record_id = path.stem
        if not ID_PATTERN.match(record_id):
            continue
        sequences[record_id] = int(record_id.split("-", 1)[1])
    return sequences


def _parse_since(since: str | None) -> tuple[str, int] | None:
    if since is None or not ID_PATTERN.match(since):
        return None
    prefix, seq = since.split("-", 1)
    return prefix, int(seq)


def _record_summary(path: Path, project_filter: str | None) -> dict | None:
    try:
        post = frontmatter.load(str(path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        logger.warning("live stream: could not parse frontmatter for %s", path, exc_info=True)
        return None

    project = post.metadata.get("project")
    if project_filter is not None and project != project_filter:
        return None

    record_id = path.stem
    prefix = record_id.split("-", 1)[0]
    title_match = H1_HEADING_RE.search(post.content or "")
    return {
        "id": record_id,
        "type": TYPE_BY_PREFIX.get(prefix) or post.metadata.get("type"),
        "title": title_match.group(1).strip() if title_match else record_id,
        "project": project,
        "date": post.metadata.get("date"),
        "status": post.metadata.get("status"),
    }


async def _record_stream_events(cfg: DaemonConfig, project: str | None, since: str | None):
    directories = (cfg.decisions_dir, cfg.lessons_dir)
    known_seq: dict[str, int] = {}
    for directory in directories:
        for record_id, seq in _record_sequences(directory).items():
            prefix = record_id[0]
            known_seq[prefix] = max(known_seq.get(prefix, 0), seq)

    parsed_since = _parse_since(since)
    if parsed_since is not None:
        prefix, seq = parsed_since
        known_seq[prefix] = seq

    needs_initial_rescan = parsed_since is not None
    dir_mtimes: dict[Path, float | None] = {
        directory: None if needs_initial_rescan else (directory.stat().st_mtime if directory.is_dir() else None)
        for directory in directories
    }

    started_at = time.monotonic()
    last_activity = time.monotonic()

    try:
        while True:
            if time.monotonic() - started_at > MAX_STREAM_SECONDS:
                return

            new_paths: list[tuple[str, int, Path]] = []
            for directory in directories:
                current_mtime = directory.stat().st_mtime if directory.is_dir() else None
                if current_mtime == dir_mtimes[directory]:
                    continue
                dir_mtimes[directory] = current_mtime
                for record_id, seq in _record_sequences(directory).items():
                    prefix = record_id[0]
                    if seq > known_seq.get(prefix, 0):
                        new_paths.append((prefix, seq, directory / f"{record_id}.md"))

            if new_paths:
                new_paths.sort(key=lambda item: (item[0], item[1]))
                for prefix, seq, path in new_paths:
                    known_seq[prefix] = max(known_seq.get(prefix, 0), seq)
                    summary = _record_summary(path, project)
                    if summary is None:
                        continue
                    yield _sse_event("record", summary)
                    last_activity = time.monotonic()

            if time.monotonic() - last_activity >= HEARTBEAT_SECONDS:
                yield _sse_event("ping", {"ts": _current_timestamp()})
                last_activity = time.monotonic()

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        return


def register_live_routes(app, cfg: DaemonConfig) -> None:
    @app.get("/api/stream/records")
    def get_records_stream(
        project: str | None = Query(default=None),
        since: str | None = Query(default=None),
    ):
        return StreamingResponse(
            _record_stream_events(cfg, project, since),
            media_type="text/event-stream",
        )
