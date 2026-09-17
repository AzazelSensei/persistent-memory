"""HTTP endpoints for the AI Council board, config, prompt layers and sessions.

`register_council_routes(app, cfg, require_token)` wires the board, prompt,
config and session routes onto an existing FastAPI app, following the
daemon's closure + `Depends(require_token)` pattern for mutations.
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from persistent_memory.council.board import (
    DEFAULT_READ_LIMIT,
    GENERAL_THREAD,
    MAX_READ_LIMIT,
    append_message,
    board_path,
    list_threads,
    read_messages,
)
from persistent_memory.council.config import (
    CONFIG_FILENAME,
    MAX_ROUNDS,
    MAX_TOTAL_TURN_CALLS,
    MEMBER_ID_PATTERN,
    CouncilConfig,
    CouncilConfigError,
    format_validation_error,
    load_council_config,
)
from persistent_memory.council.models import (
    BOARD_MESSAGE_KINDS,
    BOARD_MESSAGE_VIA,
    MAX_AUTHOR_CHARS,
    MAX_BODY_CHARS,
    MAX_PROJECT_CHARS,
    MAX_ROLE_CHARS,
    MAX_THREAD_CHARS,
)
from persistent_memory.council.prompt import (
    CouncilPromptError,
    DEFAULT_COUNCIL_PROMPT,
    MAX_PROMPT_CHARS,
    global_prompt_path,
    read_global_prompt,
    reset_global_prompt,
    resolve_prompt_layers,
    write_global_prompt,
)
from persistent_memory.council.runner import (
    COUNCIL_LOGS_DIRNAME,
    LOG_FILE_MODE,
    build_preview_prompts,
)
from persistent_memory.council.session import (
    ACTIVE_SESSION_STATUSES,
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MAX_TOPIC_CHARS,
    CouncilActiveSessionError,
    CouncilSession,
    CouncilSessionError,
    create_session,
    list_all_sessions,
    list_sessions,
    read_session,
    session_path,
    sessions_dir,
    update_session,
)

DEFAULT_POST_KIND = "note"
DEFAULT_POST_AUTHOR = "human"
DEFAULT_POST_VIA = "http"
KNOWN_NON_MEMBER_AUTHORS = ("human", "agent")

COUNCIL_CWD_ROOTS_ENV = "PM_CWD_ROOTS"
COUNCIL_PROJECT_MARKERS_GIT_DIR = ".git"

PREVIEW_SESSION_ID = "c-0000"
PENDING_THREAD_PLACEHOLDER = "pending"
COUNCIL_RUNNER_MODULE = "persistent_memory.council.runner"
LAUNCHER_LOG_SUFFIX = "-launcher.log"
CANCEL_GRACE_SECONDS = 5
CANCEL_POLL_INTERVAL_SECONDS = 0.1
PS_COMMAND_TIMEOUT_SECONDS = 2.0
PS_PROBE_SIGNAL = 0

PROMPT_VERSION_MISSING = "0"
PROMPT_VERSION_CONFLICT_ERROR = "prompt was changed elsewhere, reload and try again"

ALL_SESSIONS_TOPIC_PREVIEW_CHARS = 140

STREAM_POLL_INTERVAL_SECONDS = 1.0
STREAM_HEARTBEAT_SECONDS = 15
STREAM_MAX_SECONDS = 3600

logger = logging.getLogger(__name__)

RUNNER_EXITED_UNEXPECTEDLY_ERROR = "runner exited unexpectedly"

_council_lock = threading.Lock()
_council_procs: dict[str, tuple[str, subprocess.Popen]] = {}


def reset_council_state() -> None:
    with _council_lock:
        _council_procs.clear()


def _mark_orphaned_session_failed(council_dir: Path, project: str, session_id: str) -> None:
    try:
        session = read_session(council_dir, project, session_id)
    except CouncilSessionError:
        return
    if session.status not in ACTIVE_SESSION_STATUSES:
        return
    session = session.model_copy(
        update={"status": "failed", "finished_at": _current_timestamp(), "error": RUNNER_EXITED_UNEXPECTEDLY_ERROR}
    )
    update_session(council_dir, session)


def _prune_finished_councils(council_dir: Path) -> None:
    """Reap launcher processes that already exited.

    Nothing else polls `_council_procs`, so a launcher that dies (crash,
    OOM-kill, ...) without ever flipping its session out of pending/running
    would otherwise stay registered forever and the session would look
    "running" indefinitely. Called on every POST and every GET-list.
    """
    with _council_lock:
        finished = [
            (session_id, project) for session_id, (project, proc) in _council_procs.items() if proc.poll() is not None
        ]
        for session_id, _project in finished:
            del _council_procs[session_id]
    for session_id, project in finished:
        _mark_orphaned_session_failed(council_dir, project, session_id)


class CouncilCwdError(ValueError):
    pass


class CouncilSessionRequestError(ValueError):
    pass


class CouncilPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=MAX_PROMPT_CHARS)
    version: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


class CouncilPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(max_length=MAX_PROJECT_CHARS)
    body: str = Field(max_length=MAX_BODY_CHARS)
    thread: str = Field(default=GENERAL_THREAD, max_length=MAX_THREAD_CHARS)
    kind: str = DEFAULT_POST_KIND
    author: str = Field(default=DEFAULT_POST_AUTHOR, max_length=MAX_AUTHOR_CHARS)
    via: str = DEFAULT_POST_VIA
    role: str | None = Field(default=None, max_length=MAX_ROLE_CHARS)
    turn: int | None = None
    refs: list[str] | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in BOARD_MESSAGE_KINDS:
            raise ValueError(f"kind must be one of {BOARD_MESSAGE_KINDS}")
        return value

    @field_validator("via")
    @classmethod
    def validate_via(cls, value: str) -> str:
        if value not in BOARD_MESSAGE_VIA:
            raise ValueError(f"via must be one of {BOARD_MESSAGE_VIA}")
        return value

    @field_validator("project")
    @classmethod
    def validate_project_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project must not be empty")
        return value

    @field_validator("body")
    @classmethod
    def validate_body_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be empty")
        return value

    @field_validator("author")
    @classmethod
    def validate_author_format(cls, value: str) -> str:
        if value in KNOWN_NON_MEMBER_AUTHORS:
            return value
        if not MEMBER_ID_PATTERN.match(value):
            raise ValueError(
                f"author must match pattern {MEMBER_ID_PATTERN.pattern} or be one of {KNOWN_NON_MEMBER_AUTHORS}"
            )
        return value


class CouncilSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(max_length=MAX_PROJECT_CHARS)
    cwd: str
    topic: str = Field(max_length=MAX_TOPIC_CHARS)
    rounds: int | None = Field(default=None, ge=1, le=MAX_ROUNDS)
    members: list[str] | None = None
    dry_run: bool = False

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

    @field_validator("members")
    @classmethod
    def validate_members_not_empty_or_duplicated(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("members must not be empty")
        if len(set(value)) != len(value):
            raise ValueError(f"members must be unique, got {value}")
        return value


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _prompt_version(council_dir: Path) -> str:
    try:
        return str(global_prompt_path(council_dir).stat().st_mtime_ns)
    except FileNotFoundError:
        return PROMPT_VERSION_MISSING


def _resolve_effective_members(config: CouncilConfig, requested: list[str] | None) -> list[str]:
    members_by_id = {member.id: member for member in config.members}
    if requested is not None:
        unknown = sorted(set(requested) - members_by_id.keys())
        if unknown:
            raise CouncilSessionRequestError(f"unknown council member(s): {unknown}")
        disabled = sorted(member_id for member_id in requested if not members_by_id[member_id].enabled)
        if disabled:
            raise CouncilSessionRequestError(f"council member(s) disabled: {disabled}")
        return list(requested)
    enabled = [member.id for member in config.members if member.enabled]
    if not enabled:
        raise CouncilSessionRequestError("no enabled council members in config")
    return enabled


def _resolve_spokesperson(config: CouncilConfig, member_ids: list[str]) -> str:
    if config.spokesperson and config.spokesperson in member_ids:
        return config.spokesperson
    return member_ids[0]


def _validate_turn_call_cap(member_count: int, rounds: int) -> int:
    total_calls = member_count * rounds + 1
    if total_calls > MAX_TOTAL_TURN_CALLS:
        raise CouncilSessionRequestError(
            f"{member_count} members x {rounds} rounds + 1 synthesis = {total_calls} calls, "
            f"exceeds the cap of {MAX_TOTAL_TURN_CALLS}"
        )
    return total_calls


def _session_summary(session: CouncilSession) -> dict:
    return {
        "id": session.id,
        "project": session.project,
        "topic": session.topic,
        "thread": session.thread,
        "status": session.status,
        "rounds": session.rounds,
        "members": session.members,
        "spokesperson": session.spokesperson,
        "created_at": session.created_at,
        "finished_at": session.finished_at,
        "record_id": session.record_id,
        "error": session.error,
    }


def _truncate_topic(topic: str) -> str:
    if len(topic) <= ALL_SESSIONS_TOPIC_PREVIEW_CHARS:
        return topic
    return topic[:ALL_SESSIONS_TOPIC_PREVIEW_CHARS] + "…"


def _session_summary_all(session: CouncilSession) -> dict:
    return {
        "id": session.id,
        "project": session.project,
        "topic": _truncate_topic(session.topic),
        "status": session.status,
        "rounds": session.rounds,
        "members": session.members,
        "created_at": session.created_at,
        "finished_at": session.finished_at,
        "record_id": session.record_id,
        "thread": session.thread,
    }


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _council_stream_events(council_dir: Path, project: str, session_id: str | None):
    board_file = board_path(council_dir, project)
    session_file = session_path(council_dir, project, session_id) if session_id is not None else None

    board_mtime: float | None = None
    session_mtime: float | None = None
    since_id: str | None = None
    started_at = time.monotonic()
    last_activity = time.monotonic()

    try:
        while True:
            if time.monotonic() - started_at > STREAM_MAX_SECONDS:
                return

            current_board_mtime = board_file.stat().st_mtime if board_file.exists() else None
            if current_board_mtime != board_mtime:
                board_mtime = current_board_mtime
                messages = read_messages(council_dir, project, since=since_id, limit=MAX_READ_LIMIT)
                if messages:
                    since_id = messages[-1].id
                    for message in messages:
                        yield _sse_event("message", message.model_dump())
                    last_activity = time.monotonic()

            if session_file is not None:
                current_session_mtime = session_file.stat().st_mtime if session_file.exists() else None
                if current_session_mtime != session_mtime:
                    session_mtime = current_session_mtime
                    if session_file.exists():
                        try:
                            session = read_session(council_dir, project, session_id)
                        except CouncilSessionError:
                            logger.warning(
                                "council stream: transient read failure for session %s, retrying next poll",
                                session_id,
                            )
                        else:
                            yield _sse_event("session", session.model_dump(exclude={"project_root"}))
                            last_activity = time.monotonic()

            if time.monotonic() - last_activity >= STREAM_HEARTBEAT_SECONDS:
                yield _sse_event("ping", {"ts": _current_timestamp()})
                last_activity = time.monotonic()

            await asyncio.sleep(STREAM_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        return


def _build_dry_run_prompts(
    council_dir: Path, config: CouncilConfig, project: str, project_root: Path, topic: str, rounds: int,
    member_ids: list[str],
) -> dict[str, str]:
    preview_session = CouncilSession(
        id=PREVIEW_SESSION_ID,
        project=project,
        project_root=str(project_root),
        topic=topic,
        thread=PREVIEW_SESSION_ID,
        status="pending",
        rounds=rounds,
        members=member_ids,
        spokesperson=_resolve_spokesperson(config, member_ids),
        created_at=_current_timestamp(),
    )
    return build_preview_prompts(preview_session, config, council_dir)


def _council_cwd_roots() -> tuple[Path, ...]:
    override = os.environ.get(COUNCIL_CWD_ROOTS_ENV)
    if not override:
        return (Path.home(),)
    return tuple(Path(part) for part in override.split(os.pathsep) if part)


def _is_project_root(path: Path) -> bool:
    return (path / COUNCIL_PROJECT_MARKERS_GIT_DIR).is_dir() or (path / CONFIG_FILENAME).is_file()


def _validate_council_cwd(cwd: str) -> Path:
    if not cwd or not Path(cwd).is_absolute():
        raise CouncilCwdError("cwd must be an absolute path")
    resolved = Path(cwd).resolve()
    if not resolved.is_dir():
        raise CouncilCwdError("cwd is not an existing directory")
    for root in _council_cwd_roots():
        if resolved.is_relative_to(root.resolve()):
            if not _is_project_root(resolved):
                raise CouncilCwdError(f"cwd is not a project root (missing .git or {CONFIG_FILENAME})")
            return resolved
    raise CouncilCwdError("cwd outside allowed roots")


def _terminate_launcher(proc: subprocess.Popen) -> None:
    """Give the launcher a chance to cancel gracefully (its SIGTERM handler
    kills its own council member process groups and marks the session
    cancelled) before force-killing it. A forced SIGKILL here only reaches
    the launcher's own process group — orphaned member subprocesses are the
    launcher's responsibility, which is why the graceful path is tried first.
    """
    proc.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + CANCEL_GRACE_SECONDS
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(CANCEL_POLL_INTERVAL_SECONDS)
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        logger.warning("council: launcher process group for pid=%s already gone", proc.pid)
        proc.kill()


def _verify_pid_belongs_to_council_runner(pid: int) -> bool:
    """Confirm `pid` is actually a council runner before signalling it.

    session.json's `runner_pid`/`runner_pgid` can outlive the process they
    named (the runner finished and the OS reused the pid for something
    unrelated) — signalling blindly risks killing an unrelated process.
    """
    try:
        result = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=PS_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("council: could not verify pid=%s via ps, refusing to signal", pid, exc_info=True)
        return False
    return COUNCIL_RUNNER_MODULE in result.stdout


def _process_group_is_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, PS_PROBE_SIGNAL)
    except ProcessLookupError:
        return False
    return True


def _terminate_runner_by_pgid(pid: int, pgid: int) -> None:
    """Fallback cancel path for when `_council_procs` has lost the launcher's
    Popen handle (e.g. the daemon restarted) but session.json still carries
    the runner's own pid/pgid — the persistent, disk-backed cancel channel.
    """
    if not _verify_pid_belongs_to_council_runner(pid):
        logger.warning("council: refusing to signal pid=%s pgid=%s, not a council runner process", pid, pgid)
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        logger.warning("council: process group %s already gone before graceful cancel", pgid)
        return
    deadline = time.monotonic() + CANCEL_GRACE_SECONDS
    while time.monotonic() < deadline and _process_group_is_alive(pgid):
        time.sleep(CANCEL_POLL_INTERVAL_SECONDS)
    if not _process_group_is_alive(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        logger.warning("council: process group %s already gone before force kill", pgid)


def register_council_routes(app, cfg, require_token) -> None:
    @app.get("/api/council/board")
    def get_council_board(
        project: str = Query(...),
        thread: str | None = Query(default=None),
        since: str | None = Query(default=None),
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=MAX_READ_LIMIT),
    ):
        try:
            messages = read_messages(
                cfg.council_dir, project, thread=thread, since=since, limit=limit
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "project": project,
            "thread": thread,
            "messages": [message.model_dump() for message in messages],
            "count": len(messages),
        }

    @app.post(
        "/api/council/board",
        status_code=201,
        dependencies=[Depends(require_token)],
    )
    def post_council_board(payload: CouncilPostRequest):
        message_fields = {
            "project": payload.project,
            "thread": payload.thread,
            "author": payload.author,
            "kind": payload.kind,
            "body": payload.body,
            "via": payload.via,
            "role": payload.role,
            "turn": payload.turn,
            "refs": payload.refs or [],
        }
        try:
            message = append_message(cfg.council_dir, message_fields)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=format_validation_error(exc)
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": message.id, "thread": message.thread, "ts": message.ts}

    @app.get("/api/council/threads")
    def get_council_threads(project: str = Query(...)):
        return {"project": project, "threads": list_threads(cfg.council_dir, project)}

    @app.get("/api/council/prompt")
    def get_council_prompt():
        try:
            text = read_global_prompt(cfg.council_dir)
        except CouncilPromptError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "text": text,
            "is_default": text is None,
            "default_text": DEFAULT_COUNCIL_PROMPT,
            "version": _prompt_version(cfg.council_dir),
        }

    @app.post(
        "/api/council/prompt",
        dependencies=[Depends(require_token)],
    )
    def post_council_prompt(payload: CouncilPromptRequest):
        if payload.version is not None and payload.version != _prompt_version(cfg.council_dir):
            raise HTTPException(status_code=409, detail=PROMPT_VERSION_CONFLICT_ERROR)
        write_global_prompt(cfg.council_dir, payload.text)
        return {"status": "saved", "version": _prompt_version(cfg.council_dir)}

    @app.post(
        "/api/council/prompt/reset",
        dependencies=[Depends(require_token)],
    )
    def post_council_prompt_reset():
        reset_global_prompt(cfg.council_dir)
        return {"status": "reset"}

    @app.get("/api/council/config", dependencies=[Depends(require_token)])
    def get_council_config(
        project: str = Query(...),
        cwd: str = Query(...),
    ):
        try:
            project_root = _validate_council_cwd(cwd)
        except CouncilCwdError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            config, source = load_council_config(project_root)
        except CouncilConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            prompt_layers = resolve_prompt_layers(cfg.council_dir, config)
        except CouncilPromptError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project": project,
            "source": source,
            "config": config.model_dump(),
            "prompt_layers": prompt_layers,
        }

    @app.post(
        "/api/council/sessions",
        dependencies=[Depends(require_token)],
    )
    def post_council_session(payload: CouncilSessionCreateRequest, response: Response):
        _prune_finished_councils(cfg.council_dir)

        try:
            project_root = _validate_council_cwd(payload.cwd)
        except CouncilCwdError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            config, _source = load_council_config(project_root)
        except CouncilConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            member_ids = _resolve_effective_members(config, payload.members)
            rounds = payload.rounds if payload.rounds is not None else config.rounds
            estimated_calls = _validate_turn_call_cap(len(member_ids), rounds)
        except CouncilSessionRequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if payload.dry_run:
            prompts = _build_dry_run_prompts(
                cfg.council_dir, config, payload.project, project_root, payload.topic, rounds, member_ids
            )
            return {
                "dry_run": True,
                "project": payload.project,
                "members": member_ids,
                "rounds": rounds,
                "spokesperson": _resolve_spokesperson(config, member_ids),
                "estimated_calls": estimated_calls,
                "prompts": prompts,
            }

        try:
            session = create_session(
                cfg.council_dir,
                {
                    "project": payload.project,
                    "project_root": str(project_root),
                    "topic": payload.topic,
                    "thread": PENDING_THREAD_PLACEHOLDER,
                    "status": "pending",
                    "rounds": rounds,
                    "members": member_ids,
                    "spokesperson": _resolve_spokesperson(config, member_ids),
                },
                active_statuses=ACTIVE_SESSION_STATUSES,
            )
        except CouncilActiveSessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CouncilSessionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        session = session.model_copy(update={"thread": session.id})
        update_session(cfg.council_dir, session)

        log_dir = sessions_dir(cfg.council_dir, payload.project).parent / COUNCIL_LOGS_DIRNAME
        log_dir.mkdir(parents=True, exist_ok=True)
        launcher_log_path = log_dir / f"{session.id}{LAUNCHER_LOG_SUFFIX}"
        argv = [
            sys.executable,
            "-m",
            COUNCIL_RUNNER_MODULE,
            "--records-dir",
            str(cfg.records_dir),
            "--project",
            payload.project,
            "--session",
            session.id,
        ]
        log_handle = open(launcher_log_path, "w", encoding="utf-8")
        try:
            os.chmod(launcher_log_path, LOG_FILE_MODE)
        except OSError:
            logger.warning("council: could not chmod launcher log %s", launcher_log_path, exc_info=True)
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(project_root),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        with _council_lock:
            _council_procs[session.id] = (session.project, proc)

        response.status_code = 202
        return {
            "id": session.id,
            "project": session.project,
            "thread": session.thread,
            "members": session.members,
            "rounds": session.rounds,
            "spokesperson": session.spokesperson,
            "estimated_calls": estimated_calls,
            "log_dir": str(log_dir),
        }

    @app.get("/api/council/sessions")
    def get_council_sessions(
        project: str = Query(...),
        limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1),
    ):
        _prune_finished_councils(cfg.council_dir)
        sessions = list_sessions(cfg.council_dir, project, limit=limit)
        return {"project": project, "sessions": [_session_summary(session) for session in sessions]}

    @app.get("/api/council/sessions/all")
    def get_council_sessions_all(
        limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
        active_only: bool = Query(default=False),
    ):
        sessions = list_all_sessions(cfg.council_dir, limit=limit, active_only=active_only)
        return {"sessions": [_session_summary_all(session) for session in sessions]}

    @app.get("/api/council/stream")
    def get_council_stream(
        project: str = Query(...),
        session: str | None = Query(default=None),
    ):
        return StreamingResponse(
            _council_stream_events(cfg.council_dir, project, session),
            media_type="text/event-stream",
        )

    @app.get("/api/council/sessions/{session_id}")
    def get_council_session(session_id: str, project: str = Query(...)):
        try:
            session = read_session(cfg.council_dir, project, session_id)
        except CouncilSessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return session.model_dump(exclude={"project_root"})

    @app.post(
        "/api/council/sessions/{session_id}/cancel",
        dependencies=[Depends(require_token)],
    )
    def post_council_session_cancel(session_id: str, project: str = Query(...)):
        try:
            session = read_session(cfg.council_dir, project, session_id)
        except CouncilSessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if session.status not in ACTIVE_SESSION_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"session {session_id} already finished (status={session.status})",
            )

        with _council_lock:
            entry = _council_procs.pop(session_id, None)
        proc = entry[1] if entry is not None else None
        if proc is not None:
            if proc.poll() is None:
                _terminate_launcher(proc)
        elif session.runner_pid is not None and session.runner_pgid is not None:
            _terminate_runner_by_pgid(session.runner_pid, session.runner_pgid)

        session = session.model_copy(
            update={
                "status": "cancelled", "finished_at": _current_timestamp(),
                "runner_pid": None, "runner_pgid": None,
            }
        )
        update_session(cfg.council_dir, session)
        return {"id": session.id, "status": session.status}
