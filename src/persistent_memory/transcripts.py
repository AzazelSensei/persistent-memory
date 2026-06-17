"""Read-only access to Claude Code session transcripts (JSONL).

Discovers projects under ~/.claude/projects (filtering worktree/tmp/observer
noise) and parses transcripts into role-tagged messages. Transcripts are
append-only, which is what makes the daemon's
incremental extraction model work: the daemon keeps a per-session message-count
watermark and processes only the slice of messages added since the last run
(see daemon/services.py). This module is the parsing layer underneath that —
it never writes to a transcript.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path.home() / ".claude" / "projects"

TRANSCRIPT_GLOB = "*.jsonl"
MESSAGE_TYPES = ("user", "assistant")
TEXT_BLOCK_TYPE = "text"
TOOL_USE_BLOCK_TYPE = "tool_use"
TOOL_RESULT_BLOCK_TYPE = "tool_result"

NOISE_PATH_PREFIXES = ("/tmp", "/private/tmp")
NOISE_PATH_SUBSTRINGS = ("claude-worktrees", ".claude/worktrees", "claude-mem", "pytest-of-")
NOISE_DIR_SUBSTRINGS = ("claude-worktrees", "claude-mem-observer-sessions", "pytest-of-")

KIMI_ROOT = Path.home() / ".kimi-code"
KIMI_WIRE_FILENAME = "wire.jsonl"
KIMI_USER_MESSAGE_TYPE = "context.append_message"
KIMI_LOOP_EVENT_TYPE = "context.append_loop_event"
KIMI_TEXT_PART_TYPE = "text"
KIMI_THINK_PART_TYPE = "think"
KIMI_TOOL_CALL_EVENT_TYPE = "tool.call"
KIMI_TOOL_RESULT_EVENT_TYPE = "tool.result"

TOOL_INPUT_PREVIEW_LEN = 80


@dataclass(frozen=True)
class Message:
    role: str
    text: str
    timestamp: str | None
    is_tool: bool


@dataclass
class ProjectInfo:
    name: str
    path: str
    dir: Path
    transcript_count: int = 0
    session_ids: list[str] = field(default_factory=list)
    last_activity: str | None = None
    dirs: list[Path] = field(default_factory=list)


def _is_noise_path(path: str | None) -> bool:
    if not path:
        return True
    if any(path == prefix or path.startswith(prefix + "/") for prefix in NOISE_PATH_PREFIXES):
        return True
    if any(token in path for token in NOISE_PATH_SUBSTRINGS):
        return True
    return False


def _is_noise_dir(directory: Path) -> bool:
    return any(token in directory.name for token in NOISE_DIR_SUBSTRINGS)


def _read_jsonl_lines(jsonl_path: Path):
    try:
        with jsonl_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return


def _first_cwd(jsonl_path: Path) -> str | None:
    for obj in _read_jsonl_lines(jsonl_path):
        cwd = obj.get("cwd")
        if cwd:
            return cwd
    return None


def _last_timestamp(jsonl_path: Path) -> str | None:
    last = None
    for obj in _read_jsonl_lines(jsonl_path):
        ts = obj.get("timestamp")
        if ts:
            last = ts
    return last


def _extract_text(content) -> tuple[str, bool]:
    if isinstance(content, str):
        return content.strip(), False
    if not isinstance(content, list):
        return "", False
    texts: list[str] = []
    is_tool = False
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == TEXT_BLOCK_TYPE:
            texts.append(str(block.get("text") or ""))
        elif block_type == TOOL_USE_BLOCK_TYPE:
            is_tool = True
            texts.append(_summarize_tool_use(block))
        elif block_type == TOOL_RESULT_BLOCK_TYPE:
            is_tool = True
    return "\n".join(t for t in texts if t).strip(), is_tool


def _summarize_tool_use(block: dict) -> str:
    name = block.get("name") or "tool"
    raw = block.get("input")
    if not isinstance(raw, dict) or not raw:
        return f"[{name}]"
    parts = []
    for key, value in raw.items():
        preview = str(value)
        if len(preview) > TOOL_INPUT_PREVIEW_LEN:
            preview = preview[:TOOL_INPUT_PREVIEW_LEN] + "…"
        parts.append(f"{key}={preview}")
    return f"[{name} {' '.join(parts)}]"


def _is_kimi_transcript(jsonl_path: Path) -> bool:
    """Kimi transcripts are named wire.jsonl or live under ~/.kimi-code."""
    if jsonl_path.name == KIMI_WIRE_FILENAME:
        return True
    try:
        if jsonl_path.resolve().is_relative_to(KIMI_ROOT.resolve()):
            return True
    except (OSError, ValueError):
        pass
    return False


def _kimi_time_to_iso(time_ms: int | None) -> str | None:
    if time_ms is None:
        return None
    try:
        return datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc).isoformat()
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def _extract_kimi_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == KIMI_TEXT_PART_TYPE:
            texts.append(str(part.get("text") or ""))
    return "\n".join(t for t in texts if t).strip()


def _summarize_kimi_tool_call(event: dict) -> str:
    name = event.get("name") or "tool"
    args = event.get("args")
    if not isinstance(args, dict) or not args:
        return f"[{name}]"
    parts = []
    for key, value in args.items():
        preview = str(value)
        if len(preview) > TOOL_INPUT_PREVIEW_LEN:
            preview = preview[:TOOL_INPUT_PREVIEW_LEN] + "…"
        parts.append(f"{key}={preview}")
    return f"[{name} {' '.join(parts)}]"


def _summarize_kimi_tool_result(event: dict) -> str:
    tool_call_id = event.get("toolCallId") or event.get("parentUuid") or "?"
    return f"[tool_result {tool_call_id}]"


def _read_kimi_transcript(jsonl_path: Path) -> list[Message]:
    messages: list[Message] = []
    for obj in _read_jsonl_lines(jsonl_path):
        obj_type = obj.get("type")
        time_ms = obj.get("time")
        timestamp = _kimi_time_to_iso(time_ms)
        if obj_type == KIMI_USER_MESSAGE_TYPE:
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            origin = message.get("origin") or {}
            if isinstance(origin, dict) and origin.get("kind") != "user":
                continue
            role = message.get("role")
            if role != "user":
                continue
            text = _extract_kimi_text(message.get("content"))
            if text:
                messages.append(Message(role="user", text=text, timestamp=timestamp, is_tool=False))
        elif obj_type == KIMI_LOOP_EVENT_TYPE:
            event = obj.get("event") or {}
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "content.part":
                part = event.get("part") or {}
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type != KIMI_TEXT_PART_TYPE:
                    continue
                text = str(part.get("text") or "").strip()
                if text:
                    messages.append(Message(role="assistant", text=text, timestamp=timestamp, is_tool=False))
            elif event_type == KIMI_TOOL_CALL_EVENT_TYPE:
                text = _summarize_kimi_tool_call(event)
                messages.append(Message(role="assistant", text=text, timestamp=timestamp, is_tool=True))
            elif event_type == KIMI_TOOL_RESULT_EVENT_TYPE:
                text = _summarize_kimi_tool_result(event)
                messages.append(Message(role="user", text=text, timestamp=timestamp, is_tool=True))
    return messages


def read_transcript(jsonl_path: Path) -> list[Message]:
    if _is_kimi_transcript(jsonl_path):
        return _read_kimi_transcript(jsonl_path)
    messages: list[Message] = []
    for obj in _read_jsonl_lines(jsonl_path):
        if obj.get("type") not in MESSAGE_TYPES:
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in MESSAGE_TYPES:
            continue
        text, is_tool = _extract_text(message.get("content"))
        messages.append(
            Message(role=role, text=text, timestamp=obj.get("timestamp"), is_tool=is_tool)
        )
    return messages


def project_transcripts(project_dir: Path) -> list[Path]:
    if not project_dir.is_dir():
        return []
    return sorted(project_dir.glob(TRANSCRIPT_GLOB))


def _scan_dir(directory: Path) -> ProjectInfo | None:
    if _is_noise_dir(directory):
        return None
    transcripts = project_transcripts(directory)
    if not transcripts:
        return None
    cwd = None
    for transcript in transcripts:
        cwd = _first_cwd(transcript)
        if cwd:
            break
    if _is_noise_path(cwd):
        return None
    session_ids = [t.stem for t in transcripts]
    activities = [ts for t in transcripts if (ts := _last_timestamp(t))]
    if not activities:
        activities = [_mtime_iso(t) for t in transcripts]
    last_activity = max(activities) if activities else None
    return ProjectInfo(
        name=Path(cwd).name,
        path=cwd,
        dir=directory,
        transcript_count=len(transcripts),
        session_ids=session_ids,
        last_activity=last_activity,
        dirs=[directory],
    )


def _mtime_iso(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _merge(into: ProjectInfo, other: ProjectInfo) -> None:
    into.transcript_count += other.transcript_count
    into.session_ids.extend(other.session_ids)
    into.dirs.extend(other.dirs)
    if other.last_activity and (not into.last_activity or other.last_activity > into.last_activity):
        into.last_activity = other.last_activity


def list_projects(projects_root: Path = PROJECTS_ROOT) -> list[ProjectInfo]:
    root = Path(projects_root)
    if not root.is_dir():
        return []
    by_path: dict[str, ProjectInfo] = {}
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        info = _scan_dir(directory)
        if info is None:
            continue
        existing = by_path.get(info.path)
        if existing is None:
            by_path[info.path] = info
        else:
            _merge(existing, info)
    return sorted(by_path.values(), key=lambda p: (p.last_activity or ""), reverse=True)
