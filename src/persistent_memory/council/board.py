"""Append-only JSONL board store for the AI Council.

One board per project at `<council_dir>/<project-slug>/board.jsonl`. Writes
are serialized with an exclusive file lock so concurrent appends from
multiple sessions/threads never collide on the same message id.
"""

import fcntl
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from persistent_memory.council.models import MAX_PROJECT_CHARS, MESSAGE_ID_PATTERN, BoardMessage

logger = logging.getLogger(__name__)

BOARD_FILENAME = "board.jsonl"
DEFAULT_READ_LIMIT = 50
MAX_READ_LIMIT = 500
GENERAL_THREAD = "general"
MESSAGE_ID_WIDTH = 4
UNKNOWN_PROJECT_SLUG = "unknown"
MAX_SLUG_CHARS = 80
TAIL_READ_BYTES = 8192
PLACEHOLDER_MESSAGE_ID = "m-0000"
PLACEHOLDER_TIMESTAMP = "1970-01-01T00:00:00Z"

_SLUG_DISALLOWED_PATTERN = re.compile(r"[^a-z0-9]+")


def slugify_project(project: str) -> str:
    lowered = (project or "").lower()
    slug = _SLUG_DISALLOWED_PATTERN.sub("-", lowered).strip("-")
    slug = slug[:MAX_SLUG_CHARS].strip("-")
    return slug or UNKNOWN_PROJECT_SLUG


def board_path(council_dir: Path, project: str) -> Path:
    return Path(council_dir) / slugify_project(project) / BOARD_FILENAME


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _message_seq(message_id: str) -> int:
    if not MESSAGE_ID_PATTERN.match(message_id):
        raise ValueError(f"invalid message id: {message_id!r}")
    return int(message_id.split("-", 1)[1])


def _extract_last_valid_id(chunk_lines: list[bytes]) -> str | None:
    for line in reversed(chunk_lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        message_id = raw.get("id") if isinstance(raw, dict) else None
        if isinstance(message_id, str) and MESSAGE_ID_PATTERN.match(message_id):
            return message_id
    return None


def _last_message_id(handle) -> str | None:
    handle.seek(0, 2)
    file_size = handle.tell()
    if file_size == 0:
        return None

    read_size = min(TAIL_READ_BYTES, file_size)
    while True:
        handle.seek(file_size - read_size)
        chunk = handle.read(read_size)
        last_id = _extract_last_valid_id(chunk.split(b"\n"))
        if last_id is not None:
            return last_id
        if read_size >= file_size:
            return None
        read_size = min(read_size * 2, file_size)


def append_message(council_dir: Path, message_fields: dict) -> BoardMessage:
    if "project" not in message_fields:
        raise ValueError("message_fields must include 'project'")
    project = message_fields["project"]
    if len(project) > MAX_PROJECT_CHARS:
        raise ValueError(f"project must be at most {MAX_PROJECT_CHARS} characters")

    fields = {k: v for k, v in message_fields.items() if k not in ("id", "ts")}
    BoardMessage(id=PLACEHOLDER_MESSAGE_ID, ts=PLACEHOLDER_TIMESTAMP, **fields)

    path = board_path(council_dir, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    with open(path, "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            last_id = _last_message_id(handle)
            next_seq = _message_seq(last_id) + 1 if last_id is not None else 1
            message = BoardMessage(
                id=f"m-{next_seq:0{MESSAGE_ID_WIDTH}d}",
                ts=_current_timestamp(),
                **fields,
            )
            handle.seek(0, 2)
            file_size = handle.tell()
            payload = message.model_dump_json() + "\n"
            if file_size > 0:
                handle.seek(file_size - 1)
                if handle.read(1) != b"\n":
                    payload = "\n" + payload
                handle.seek(0, 2)
            handle.write(payload.encode("utf-8"))
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return message


def _parse_message_line(line: bytes) -> BoardMessage | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        decoded = stripped.decode("utf-8")
        raw = json.loads(decoded)
        return BoardMessage.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        logger.warning("council board: skipping corrupt line", exc_info=True)
        return None


def _read_all_messages(path: Path) -> list[BoardMessage]:
    if not path.exists():
        return []
    messages = []
    for line in path.read_bytes().split(b"\n"):
        message = _parse_message_line(line)
        if message is not None:
            messages.append(message)
    return messages


def _iter_lines_reverse(handle, file_size: int):
    """Yield raw line bytes (no trailing newline), from the file's last line
    to its first, reading backward in growing blocks (same TAIL_READ_BYTES
    doubling pattern as `_last_message_id`). Each byte is read at most once.
    """
    pos = file_size
    carry = b""
    block_size = min(TAIL_READ_BYTES, file_size)
    while pos > 0:
        read_size = min(block_size, pos)
        pos -= read_size
        handle.seek(pos)
        chunk = handle.read(read_size) + carry
        parts = chunk.split(b"\n")
        if pos > 0:
            carry = parts[0]
            complete = parts[1:]
        else:
            complete = parts
        for line in reversed(complete):
            yield line
        block_size = min(block_size * 2, pos) if pos > 0 else block_size


def _read_messages_backward(
    path: Path,
    project: str,
    thread: str | None,
    since_seq: int | None,
    limit: int,
) -> list[BoardMessage]:
    if not path.exists():
        return []

    collected: list[BoardMessage] = []
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        file_size = handle.tell()
        for line in _iter_lines_reverse(handle, file_size):
            message = _parse_message_line(line)
            if message is None:
                continue
            if since_seq is not None and _message_seq(message.id) <= since_seq:
                break
            if message.project != project:
                continue
            if thread is not None and message.thread != thread:
                continue
            collected.append(message)
            if since_seq is None and len(collected) >= limit:
                break

    collected.reverse()
    if since_seq is not None:
        return collected[:limit]
    return collected


def read_messages(
    council_dir: Path,
    project: str,
    thread: str | None = None,
    since: str | None = None,
    limit: int = DEFAULT_READ_LIMIT,
) -> list[BoardMessage]:
    clipped_limit = min(limit, MAX_READ_LIMIT)
    if clipped_limit <= 0:
        return []

    since_seq = _message_seq(since) if since is not None else None
    path = board_path(council_dir, project)
    return _read_messages_backward(path, project, thread, since_seq, clipped_limit)


def list_threads(council_dir: Path, project: str) -> list[dict]:
    path = board_path(council_dir, project)
    messages = [message for message in _read_all_messages(path) if message.project == project]

    threads: dict[str, dict] = {}
    for message in messages:
        entry = threads.setdefault(
            message.thread,
            {"thread": message.thread, "count": 0, "last_ts": message.ts, "authors": [], "_last_seq": 0},
        )
        entry["count"] += 1
        entry["last_ts"] = message.ts
        entry["_last_seq"] = _message_seq(message.id)
        if message.author not in entry["authors"]:
            entry["authors"].append(message.author)

    ordered = sorted(threads.values(), key=lambda entry: (entry["last_ts"], entry["_last_seq"]), reverse=True)
    for entry in ordered:
        entry.pop("_last_seq", None)
    return ordered
