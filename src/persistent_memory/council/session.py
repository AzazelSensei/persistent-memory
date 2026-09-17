"""Session model and file store for the AI Council.

One session directory per project at `<council_dir>/<project-slug>/sessions/`,
one `c-NNNN.json` file per session. Session ids are assigned by scanning the
directory for the highest existing sequence number (sessions are few, so an
O(dir listing) scan is cheap — unlike the board's O(file) tail-read
optimization). Writes are atomic (tempfile + os.replace) and serialized with
an exclusive file lock so two concurrent `create_session` calls never mint
the same id, and two concurrent `update_session` calls on the same session
never interleave into a corrupt file.
"""

import fcntl
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from persistent_memory.council.board import slugify_project
from persistent_memory.council.config import MEMBER_ID_PATTERN, format_validation_error
from persistent_memory.council.models import MAX_PROJECT_CHARS, MAX_THREAD_CHARS

logger = logging.getLogger(__name__)

SESSIONS_SUBDIR = "sessions"
SESSION_ID_PATTERN = re.compile(r"^c-\d{4,}$")
SESSION_ID_WIDTH = 4
LOCK_FILENAME = ".sessions.lock"
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 500

MAX_TOPIC_CHARS = 2000

COUNCIL_SESSION_STATUSES = ("pending", "running", "converged", "failed", "cancelled")
COUNCIL_TURN_STATUSES = ("pending", "running", "done", "failed", "timeout", "skipped", "cancelled")
ACTIVE_SESSION_STATUSES = ("pending", "running")


class CouncilSessionError(ValueError):
    pass


class CouncilActiveSessionError(CouncilSessionError):
    def __init__(self, active_session_id: str):
        self.active_session_id = active_session_id
        super().__init__(f"project already has an active council session: {active_session_id}")


class CouncilTurnState(BaseModel):
    """State of one member's turn within one round of a council session."""

    model_config = ConfigDict(extra="forbid")

    round: int = Field(ge=1)
    member_id: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    message_id: str | None = None
    via: str | None = None
    error: str | None = None

    @field_validator("member_id")
    @classmethod
    def validate_member_id_format(cls, value: str) -> str:
        if not MEMBER_ID_PATTERN.match(value):
            raise ValueError(f"member_id {value!r} must match pattern {MEMBER_ID_PATTERN.pattern}")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in COUNCIL_TURN_STATUSES:
            raise ValueError(f"status must be one of {COUNCIL_TURN_STATUSES}")
        return value


class CouncilSession(BaseModel):
    """A council session: one topic, N members, M rounds, one spokesperson."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project: str = Field(max_length=MAX_PROJECT_CHARS)
    project_root: str
    topic: str = Field(max_length=MAX_TOPIC_CHARS)
    thread: str = Field(max_length=MAX_THREAD_CHARS)
    status: str
    rounds: int = Field(ge=1)
    members: list[str]
    spokesperson: str
    created_at: str
    finished_at: str | None = None
    turns: list[CouncilTurnState] = Field(default_factory=list)
    record_id: str | None = None
    error: str | None = None
    runner_pid: int | None = None
    runner_pgid: int | None = None

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, value: str) -> str:
        if not SESSION_ID_PATTERN.match(value):
            raise ValueError("id must match the format c-NNNN")
        return value

    @field_validator("project")
    @classmethod
    def validate_project_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project must not be empty")
        return value

    @field_validator("topic")
    @classmethod
    def validate_topic_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("topic must not be empty")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in COUNCIL_SESSION_STATUSES:
            raise ValueError(f"status must be one of {COUNCIL_SESSION_STATUSES}")
        return value

    @field_validator("members")
    @classmethod
    def validate_member_ids(cls, value: list[str]) -> list[str]:
        for member_id in value:
            if not MEMBER_ID_PATTERN.match(member_id):
                raise ValueError(f"member id {member_id!r} must match pattern {MEMBER_ID_PATTERN.pattern}")
        return value

    @field_validator("spokesperson")
    @classmethod
    def validate_spokesperson_format(cls, value: str) -> str:
        if not MEMBER_ID_PATTERN.match(value):
            raise ValueError(f"spokesperson {value!r} must match pattern {MEMBER_ID_PATTERN.pattern}")
        return value


def sessions_dir(council_dir: Path, project: str) -> Path:
    return Path(council_dir) / slugify_project(project) / SESSIONS_SUBDIR


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _session_seq(session_id: str) -> int:
    if not SESSION_ID_PATTERN.match(session_id):
        raise ValueError(f"invalid session id: {session_id!r}")
    return int(session_id.split("-", 1)[1])


def _session_path(council_dir: Path, project: str, session_id: str) -> Path:
    return sessions_dir(council_dir, project) / f"{session_id}.json"


def session_path(council_dir: Path, project: str, session_id: str) -> Path:
    return _session_path(council_dir, project, session_id)


def next_session_id(council_dir: Path, project: str) -> str:
    directory = sessions_dir(council_dir, project)
    highest = 0
    if directory.is_dir():
        for entry in directory.glob("c-*.json"):
            try:
                seq = _session_seq(entry.stem)
            except ValueError:
                continue
            highest = max(highest, seq)
    return f"c-{highest + 1:0{SESSION_ID_WIDTH}d}"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_name, path)
        succeeded = True
    finally:
        if not succeeded and os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _with_project_lock(council_dir: Path, project: str, action):
    directory = sessions_dir(council_dir, project)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / LOCK_FILENAME
    with open(lock_path, "a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            return action()
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def create_session(
    council_dir: Path, fields: dict, active_statuses: tuple[str, ...] | None = None
) -> CouncilSession:
    if "project" not in fields:
        raise CouncilSessionError("fields must include 'project'")
    project = fields["project"]

    def _create() -> CouncilSession:
        if active_statuses is not None:
            active = [s for s in list_sessions(council_dir, project) if s.status in active_statuses]
            if active:
                raise CouncilActiveSessionError(active[0].id)
        session_id = next_session_id(council_dir, project)
        session_fields = {k: v for k, v in fields.items() if k not in ("id", "created_at")}
        try:
            session = CouncilSession(id=session_id, created_at=_current_timestamp(), **session_fields)
        except ValidationError as exc:
            raise CouncilSessionError(format_validation_error(exc)) from exc
        _write_json_atomic(_session_path(council_dir, project, session_id), session.model_dump())
        return session

    return _with_project_lock(council_dir, project, _create)


def read_session(council_dir: Path, project: str, session_id: str) -> CouncilSession:
    path = _session_path(council_dir, project, session_id)
    if not path.exists():
        raise CouncilSessionError(f"session not found: {session_id}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CouncilSessionError(f"corrupt session file {path.name}: {exc}") from exc
    try:
        return CouncilSession.model_validate(raw)
    except ValidationError as exc:
        raise CouncilSessionError(format_validation_error(exc)) from exc


def list_sessions(council_dir: Path, project: str, limit: int = DEFAULT_LIST_LIMIT) -> list[CouncilSession]:
    directory = sessions_dir(council_dir, project)
    if not directory.is_dir():
        return []
    sessions: list[CouncilSession] = []
    for entry in directory.glob("c-*.json"):
        try:
            raw = json.loads(entry.read_text(encoding="utf-8"))
            sessions.append(CouncilSession.model_validate(raw))
        except (OSError, json.JSONDecodeError, ValidationError):
            continue
    sessions.sort(key=lambda session: _session_seq(session.id), reverse=True)
    if limit is not None:
        sessions = sessions[:limit]
    return sessions


def list_all_sessions(
    council_dir: Path, limit: int = DEFAULT_LIST_LIMIT, active_only: bool = False
) -> list[CouncilSession]:
    """List sessions across every project directory under `council_dir`.

    Reads every session file in every project's `sessions/` subdirectory —
    acceptable because the total session count is small — then sorts active
    sessions (pending/running) first, each group ordered by created_at
    descending, and applies `active_only` / `limit` after sorting so results
    stay correct regardless of scan order.
    """
    root = Path(council_dir)
    if not root.is_dir():
        return []

    sessions: list[CouncilSession] = []
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        directory = project_dir / SESSIONS_SUBDIR
        if not directory.is_dir():
            continue
        for entry in directory.glob("c-*.json"):
            try:
                raw = json.loads(entry.read_text(encoding="utf-8"))
                sessions.append(CouncilSession.model_validate(raw))
            except (OSError, json.JSONDecodeError, ValidationError):
                logger.warning("council: skipping corrupt session file %s", entry, exc_info=True)
                continue

    if active_only:
        sessions = [session for session in sessions if session.status in ACTIVE_SESSION_STATUSES]

    sessions.sort(key=lambda session: (session.created_at, _session_seq(session.id)), reverse=True)
    sessions.sort(key=lambda session: session.status not in ACTIVE_SESSION_STATUSES)
    return sessions[:limit]


def update_session(council_dir: Path, session: CouncilSession) -> None:
    def _update() -> None:
        path = _session_path(council_dir, session.project, session.id)
        _write_json_atomic(path, session.model_dump())

    _with_project_lock(council_dir, session.project, _update)


def update_session_with(
    council_dir: Path, project: str, session_id: str, mutate: Callable[[CouncilSession], CouncilSession]
) -> CouncilSession:
    """Read-modify-write a session file under the project lock.

    Reads the current on-disk session, applies `mutate` to it, writes the
    result back and returns it — all under one lock acquisition, so a
    concurrent writer (e.g. an API cancel request) can never be silently
    overwritten by a stale in-memory copy.
    """

    def _update() -> CouncilSession:
        current = read_session(council_dir, project, session_id)
        updated = mutate(current)
        _write_json_atomic(_session_path(council_dir, project, session_id), updated.model_dump())
        return updated

    return _with_project_lock(council_dir, project, _update)
