"""Turn engine for the AI Council: runs rounds, captures answers, synthesizes.

Runs as a detached process (`python -m persistent_memory.council.runner`),
separate from the daemon so a long deliberation survives a daemon restart
(see the design doc, section 5). All external effects — spawning the CLI
subprocess, reading the clock, searching memory, writing the resulting
decision record — go through `RunnerDeps` so `run_council_session` can be
exercised without real subprocesses, real time, the daemon's search index,
or the daemon's record-write API. `main()` wires the real dependencies.

Member prompts never travel on argv (readable by any local process via
`ps`/`/proc`): each turn's full prompt is written to a private
0600 file under `council-prompts/` and the member CLI is given a short
instruction plus the file path instead (see `_write_turn_prompt_file`).
"""

import argparse
import logging
import os
import re
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from persistent_memory.council.backends import (
    build_council_argv,
    build_council_env,
    extract_answer,
    resolve_backend_bin,
)
from persistent_memory.council.board import MAX_READ_LIMIT, append_message, read_messages
from persistent_memory.council.config import (
    CouncilConfig,
    CouncilConfigError,
    CouncilMember,
    load_council_config,
)
from persistent_memory.council.models import MAX_ROLE_CHARS, BoardMessage
from persistent_memory.council.prompt import compose_council_prompt
from persistent_memory.council.session import (
    CouncilSession,
    CouncilSessionError,
    CouncilTurnState,
    read_session,
    sessions_dir,
    update_session,
    update_session_with,
)

logger = logging.getLogger(__name__)

QUESTION_HEADER = "## Question"
MEMORY_HEADER = "## Relevant memory"
BOARD_HEADER = "## Board so far"
YOUR_TURN_HEADER = "## Your turn"

ROUND_ONE_INSTRUCTION = (
    "This is round 1 of {total_rounds}. The other members are answering at the "
    "same time; you cannot see their answers yet."
)
LATER_ROUND_INSTRUCTION = (
    "This is round {round_number} of {total_rounds}. Read the board above, then "
    "state where you agree, where you disagree, and what changed your mind."
)
SYNTHESIS_INSTRUCTION = (
    "You are the spokesperson. Write the final synthesis: the consensus, the "
    "open disagreements (name them), and the decision with its rationale."
)
NO_SELF_WRITE_NOTICE = (
    "Do not write to the board yourself and do not create records. Do not call "
    "council_post, council_read is fine for reading, and never call create_record. "
    "Your answer is captured automatically from your output - writing it yourself "
    "creates duplicates."
)
MEMBER_IDENTITY_NOTICE_TEMPLATE = (
    'Your member id in this council is "{member_id}". If you ever post to the '
    'board, you must pass author="{member_id}".'
)

BOARD_MESSAGES_TAG = "board_messages"
MSG_TAG = "msg"
MAX_PROMPT_CHARS_TOTAL = 60000

HEADING_ESCAPE_PATTERN = re.compile(r"(?m)^([ \t]*)## ")
HEADING_ESCAPE_REPLACEMENT = r"\1\\#\\# "

COUNCIL_LOGS_DIRNAME = "council-logs"
COUNCIL_PROMPTS_DIRNAME = "council-prompts"
PROMPT_DIR_MODE = 0o700
PROMPT_FILE_MODE = 0o600
LOG_FILE_MODE = 0o600
COUNCIL_PROMPT_FILE_INSTRUCTION = "Read the file at {path} and follow it. It contains your full instructions."

KIND_PROPOSAL = "proposal"
KIND_CRITIQUE = "critique"
KIND_DECISION = "decision"

STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_SKIPPED = "skipped"
STATUS_CANCELLED = "cancelled"

VIA_STDOUT = "stdout"

NO_AVAILABLE_MEMBERS_ERROR = "no council member is available (all skipped or unresolved)"
SYNTHESIS_FAILED_ERROR = "synthesis failed: no spokesperson could produce an answer"
SYNTHESIS_EMPTY_ERROR = "synthesis text is empty"
EMPTY_RESPONSE_ERROR = "empty response"
RECORD_WRITE_FAILED_ERROR = "council record could not be written"
WALL_CLOCK_EXCEEDED_ERROR = "session wall-clock cap exceeded"
MAX_ERROR_CHARS = 500

COUNCIL_ERROR_SIGNATURES = (
    "Not logged in",
    "Please run /login",
    "usage limit",
    "quota",
    "rate limit",
    "command not found",
)
CLI_ERROR_MAX_ANSWER_CHARS = 400

MEMORY_SEARCH_TOP_K = 5
COUNCIL_SEARCH_PATH = "/api/search"
SEARCH_TIMEOUT_SECONDS = 10.0
DRY_RUN_MEMORY_NOTICE = "(memory lookup skipped in dry-run)"

COUNCIL_RECORD_TYPE = "decision"
COUNCIL_RECORD_TAGS = ["council"]
COUNCIL_RECORD_AGENT = "council"
SOURCE_SECTION_HEADER = "## Source (council)"
MAX_RECORD_TITLE_CHARS = 120
TITLE_ELLIPSIS = "…"

RECORD_WRITE_TIMEOUT_SECONDS = 30.0

MAX_SESSION_SECONDS = 3600

CANCEL_POLL_SECONDS = 5.0


@dataclass
class SpawnRequest:
    argv: list[str]
    executable: str
    cwd: str
    env: dict
    log_path: Path


@dataclass
class RunnerDeps:
    spawn: Callable[[SpawnRequest], Any]
    now: Callable[[], str]
    search_memory: Callable[[str, str], list[str]]
    create_record: Callable[[dict], str | None]


@dataclass
class Participant:
    member: CouncilMember
    bin_path: str
    env: dict


@dataclass
class TurnContext:
    config: CouncilConfig
    council_dir: Path
    session: CouncilSession
    deps: RunnerDeps
    memory_lines: list[str] = field(default_factory=list)


@dataclass
class RoundSpec:
    round_number: int
    kind: str


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _seconds_elapsed(start_ts: str, now_ts: str) -> float:
    return (_parse_timestamp(now_ts) - _parse_timestamp(start_ts)).total_seconds()


def _kind_for_round(round_number: int) -> str:
    return KIND_PROPOSAL if round_number == 1 else KIND_CRITIQUE


def _board_role(role: str | None) -> str | None:
    if not role:
        return None
    return role[:MAX_ROLE_CHARS]


def _wrap_board_messages(text: str) -> str:
    safe_text = text.replace(f"</{BOARD_MESSAGES_TAG}>", f"<\\/{BOARD_MESSAGES_TAG}>")
    safe_text = safe_text.replace(f"<{BOARD_MESSAGES_TAG}>", f"<\\{BOARD_MESSAGES_TAG}>")
    return f"<{BOARD_MESSAGES_TAG}>\n{safe_text}\n</{BOARD_MESSAGES_TAG}>"


def _escape_guarded_body(text: str) -> str:
    safe_text = text.replace(f"</{MSG_TAG}", f"<\\/{MSG_TAG}")
    safe_text = safe_text.replace(f"<{MSG_TAG}", f"<\\{MSG_TAG}")
    safe_text = safe_text.replace(f"</{BOARD_MESSAGES_TAG}>", f"<\\/{BOARD_MESSAGES_TAG}>")
    safe_text = safe_text.replace(f"<{BOARD_MESSAGES_TAG}>", f"<\\{BOARD_MESSAGES_TAG}>")
    return HEADING_ESCAPE_PATTERN.sub(HEADING_ESCAPE_REPLACEMENT, safe_text)


def _escape_attribute(text: str) -> str:
    return _escape_guarded_body(text).replace('"', '\\"')


def _format_board_message(message: BoardMessage) -> str:
    body = _escape_guarded_body(message.body)
    round_attr = message.turn if message.turn is not None else ""
    role_attr = f' role="{_escape_attribute(message.role)}"' if message.role else ""
    return (
        f'<{MSG_TAG} id="{message.id}" author="{message.author}" round="{round_attr}" '
        f'kind="{message.kind}" via="{message.via}"{role_attr}>\n{body}\n</{MSG_TAG}>'
    )


def _your_turn_section(round_spec: RoundSpec, total_rounds: int, member_id: str) -> str:
    if round_spec.kind == KIND_DECISION:
        text = SYNTHESIS_INSTRUCTION
    elif round_spec.round_number == 1:
        text = ROUND_ONE_INSTRUCTION.format(total_rounds=total_rounds)
    else:
        text = LATER_ROUND_INSTRUCTION.format(round_number=round_spec.round_number, total_rounds=total_rounds)
    identity_notice = MEMBER_IDENTITY_NOTICE_TEMPLATE.format(member_id=member_id)
    return f"{YOUR_TURN_HEADER}\n\n{text}\n\n{identity_notice}\n\n{NO_SELF_WRITE_NOTICE}"


def _prompt_for_remaining(sections: list[str], remaining: list[BoardMessage], your_turn_text: str) -> str:
    parts = list(sections)
    if remaining:
        board_text = "\n\n".join(_format_board_message(message) for message in remaining)
        parts.append(f"{BOARD_HEADER}\n\n{_wrap_board_messages(board_text)}")
    parts.append(your_turn_text)
    return "\n\n".join(parts)


def _compose_with_board_budget(sections: list[str], board_messages: list[BoardMessage], your_turn_text: str) -> str:
    total = len(board_messages)
    low, high = 0, total
    while low < high:
        mid = (low + high) // 2
        remaining = board_messages[mid:]
        if not remaining or len(_prompt_for_remaining(sections, remaining, your_turn_text)) <= MAX_PROMPT_CHARS_TOTAL:
            high = mid
        else:
            low = mid + 1
    return _prompt_for_remaining(sections, board_messages[low:], your_turn_text)


def _build_turn_prompt(ctx: TurnContext, member: CouncilMember, round_spec: RoundSpec) -> str:
    session = ctx.session
    sections = [compose_council_prompt(ctx.council_dir, ctx.config, member), f"{QUESTION_HEADER}\n\n{session.topic}"]

    if ctx.memory_lines:
        sections.append(f"{MEMORY_HEADER}\n\n" + "\n".join(ctx.memory_lines))

    board_messages: list[BoardMessage] = []
    if round_spec.round_number > 1:
        board_messages = read_messages(ctx.council_dir, session.project, thread=session.thread, limit=MAX_READ_LIMIT)

    your_turn_text = _your_turn_section(round_spec, session.rounds, member.id)
    return _compose_with_board_budget(sections, board_messages, your_turn_text)


def _reject_runner_dependency_call(*_args, **_kwargs):
    raise RuntimeError("preview prompt construction must not invoke runner dependencies")


def build_preview_prompts(session: CouncilSession, config: CouncilConfig, council_dir: Path) -> dict[str, str]:
    """Build every member's round-1 prompt without spawning or writing anything.

    Public surface for the dry-run session endpoint (`council/api.py`) to
    preview what a real run would send each member. Round-1 prompts never
    read the board or call `search_memory`/`create_record`, so this needs no
    real `RunnerDeps` — a deps object that raises on any call is used, so a
    future change that accidentally wires round 2+ through here fails loudly
    instead of spawning a real subprocess during a preview.
    """
    members_by_id = {member.id: member for member in config.members}
    deps = RunnerDeps(
        spawn=_reject_runner_dependency_call,
        now=_reject_runner_dependency_call,
        search_memory=_reject_runner_dependency_call,
        create_record=_reject_runner_dependency_call,
    )
    ctx = TurnContext(
        config=config, council_dir=council_dir, session=session, deps=deps, memory_lines=[DRY_RUN_MEMORY_NOTICE]
    )
    round_spec = RoundSpec(round_number=1, kind=_kind_for_round(1))
    return {member_id: _build_turn_prompt(ctx, members_by_id[member_id], round_spec) for member_id in session.members}


def _turn_log_path(council_dir: Path, session: CouncilSession, round_spec: RoundSpec, member: CouncilMember) -> Path:
    directory = sessions_dir(council_dir, session.project).parent / COUNCIL_LOGS_DIRNAME
    return directory / f"{session.id}-r{round_spec.round_number}-{member.id}.log"


def _turn_prompt_path(council_dir: Path, session: CouncilSession, round_spec: RoundSpec, member: CouncilMember) -> Path:
    directory = sessions_dir(council_dir, session.project).parent / COUNCIL_PROMPTS_DIRNAME
    return directory / f"{session.id}-r{round_spec.round_number}-{member.id}.txt"


def _write_turn_prompt_file(
    council_dir: Path, session: CouncilSession, round_spec: RoundSpec, member: CouncilMember, prompt: str
) -> Path:
    path = _turn_prompt_path(council_dir, session, round_spec, member)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, PROMPT_DIR_MODE)
    path.write_text(prompt, encoding="utf-8")
    os.chmod(path, PROMPT_FILE_MODE)
    return path


def _find_message_by_id(council_dir: Path, project: str, thread: str, message_id: str | None) -> BoardMessage | None:
    if message_id is None:
        return None
    for message in read_messages(council_dir, project, thread=thread, limit=MAX_READ_LIMIT):
        if message.id == message_id:
            return message
    return None


def _looks_like_cli_error(answer: str) -> bool:
    if len(answer) >= CLI_ERROR_MAX_ANSWER_CHARS:
        return False
    lowered = answer.lower()
    return any(signature.lower() in lowered for signature in COUNCIL_ERROR_SIGNATURES)


def _resolve_pgid(proc: Any) -> int | None:
    pid = getattr(proc, "pid", None)
    if pid is None:
        return None
    try:
        return os.getpgid(pid)
    except ProcessLookupError:
        return None


def _kill_proc_or_group(proc: Any, pgid: int | None) -> None:
    if pgid is None:
        proc.kill()
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        logger.warning("council: process group %s already exited before kill", pgid)


class _TurnCancelled(Exception):
    """Raised out of `_wait_with_cancel_polling` when the session was cancelled mid-wait."""


def _wait_with_cancel_polling(
    proc: Any, proc_pgid: int | None, total_timeout_seconds: float, council_dir: Path, session: CouncilSession
) -> int:
    """Wait for `proc` in `CANCEL_POLL_SECONDS` slices instead of one blocking call.

    A single `proc.wait(timeout=total_timeout_seconds)` call only notices
    cancellation once it returns — for a long-running member CLI that means
    the whole timeout window. Polling in short slices and re-reading
    session.json between slices lets a cancel land within one poll interval
    instead of the full turn timeout.
    """
    elapsed = 0.0
    while True:
        remaining = total_timeout_seconds - elapsed
        if remaining <= 0:
            raise subprocess.TimeoutExpired(cmd="council-member", timeout=total_timeout_seconds)
        poll_seconds = min(CANCEL_POLL_SECONDS, remaining)
        try:
            return proc.wait(timeout=poll_seconds)
        except subprocess.TimeoutExpired:
            elapsed += poll_seconds
            if _is_cancelled(council_dir, session):
                _kill_proc_or_group(proc, proc_pgid)
                raise _TurnCancelled() from None


_ACTIVE_PROCESS_LOCK = threading.Lock()
_ACTIVE_PGIDS: set[int] = set()


def _register_active_pgid(pgid: int) -> None:
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PGIDS.add(pgid)


def _unregister_active_pgid(pgid: int) -> None:
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PGIDS.discard(pgid)


def _kill_all_active_process_groups() -> None:
    with _ACTIVE_PROCESS_LOCK:
        pgids = list(_ACTIVE_PGIDS)
    for pgid in pgids:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            logger.warning("council: process group %s already exited before cancel", pgid)
        _unregister_active_pgid(pgid)


def _run_single_turn(ctx: TurnContext, participant: Participant, round_spec: RoundSpec) -> CouncilTurnState:
    session = ctx.session
    member = participant.member
    started_at = ctx.deps.now()
    prompt = _build_turn_prompt(ctx, member, round_spec)
    log_path = _turn_log_path(ctx.council_dir, session, round_spec, member)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    prompt_path = _write_turn_prompt_file(ctx.council_dir, session, round_spec, member, prompt)
    instruction = COUNCIL_PROMPT_FILE_INSTRUCTION.format(path=prompt_path)
    argv = build_council_argv(member.backend, instruction, session.project_root, model=member.model, effort=member.effort)
    request = SpawnRequest(
        argv=argv, executable=participant.bin_path, cwd=session.project_root, env=participant.env, log_path=log_path
    )

    try:
        proc = ctx.deps.spawn(request)
    except OSError as exc:
        return CouncilTurnState(
            round=round_spec.round_number, member_id=member.id, status=STATUS_FAILED,
            started_at=started_at, finished_at=ctx.deps.now(), error=str(exc),
        )

    proc_pgid = _resolve_pgid(proc)
    try:
        try:
            exit_code = _wait_with_cancel_polling(
                proc, proc_pgid, ctx.config.turn_timeout_seconds, ctx.council_dir, ctx.session
            )
        except _TurnCancelled:
            return CouncilTurnState(
                round=round_spec.round_number, member_id=member.id, status=STATUS_CANCELLED,
                started_at=started_at, finished_at=ctx.deps.now(),
            )
        except subprocess.TimeoutExpired:
            _kill_proc_or_group(proc, proc_pgid)
            return CouncilTurnState(
                round=round_spec.round_number, member_id=member.id, status=STATUS_TIMEOUT,
                started_at=started_at, finished_at=ctx.deps.now(), error="turn timed out",
            )
    finally:
        if proc_pgid is not None:
            _unregister_active_pgid(proc_pgid)

    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

    if exit_code != 0:
        return CouncilTurnState(
            round=round_spec.round_number, member_id=member.id, status=STATUS_FAILED,
            started_at=started_at, finished_at=ctx.deps.now(), exit_code=exit_code,
            error=log_text[:MAX_ERROR_CHARS] or f"exit code {exit_code}",
        )

    answer = extract_answer(member.backend, log_text)
    if not answer:
        return CouncilTurnState(
            round=round_spec.round_number, member_id=member.id, status=STATUS_FAILED,
            started_at=started_at, finished_at=ctx.deps.now(), exit_code=exit_code, error=EMPTY_RESPONSE_ERROR,
        )

    if _looks_like_cli_error(answer):
        return CouncilTurnState(
            round=round_spec.round_number, member_id=member.id, status=STATUS_FAILED,
            started_at=started_at, finished_at=ctx.deps.now(), exit_code=exit_code, error=answer[:MAX_ERROR_CHARS],
        )

    message = append_message(
        ctx.council_dir,
        {
            "project": session.project, "thread": session.thread, "author": member.id,
            "role": _board_role(member.role), "kind": round_spec.kind, "body": answer, "via": VIA_STDOUT,
            "turn": round_spec.round_number, "refs": [],
        },
    )
    return CouncilTurnState(
        round=round_spec.round_number, member_id=member.id, status=STATUS_DONE,
        started_at=started_at, finished_at=ctx.deps.now(), exit_code=exit_code,
        message_id=message.id, via=VIA_STDOUT,
    )


def _run_single_turn_safe(ctx: TurnContext, participant: Participant, round_spec: RoundSpec) -> CouncilTurnState:
    try:
        return _run_single_turn(ctx, participant, round_spec)
    except Exception as exc:
        logger.exception(
            "council turn raised for member=%s round=%s", participant.member.id, round_spec.round_number
        )
        timestamp = ctx.deps.now()
        return CouncilTurnState(
            round=round_spec.round_number, member_id=participant.member.id, status=STATUS_FAILED,
            started_at=timestamp, finished_at=timestamp, error=str(exc)[:MAX_ERROR_CHARS],
        )


def _run_round_parallel(ctx: TurnContext, participants: list[Participant], round_spec: RoundSpec) -> list[CouncilTurnState]:
    results: list[CouncilTurnState | None] = [None] * len(participants)

    def _worker(index: int, participant: Participant) -> None:
        results[index] = _run_single_turn_safe(ctx, participant, round_spec)

    threads = [threading.Thread(target=_worker, args=(index, participant)) for index, participant in enumerate(participants)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return [result for result in results if result is not None]


def _run_round_sequential(ctx: TurnContext, participants: list[Participant], round_spec: RoundSpec) -> list[CouncilTurnState]:
    results: list[CouncilTurnState] = []
    for participant in participants:
        if _is_cancelled(ctx.council_dir, ctx.session):
            break
        results.append(_run_single_turn_safe(ctx, participant, round_spec))
    return results


def _build_participants(
    config: CouncilConfig, session: CouncilSession, deps: RunnerDeps
) -> tuple[list[Participant], list[CouncilTurnState]]:
    members_by_id = {member.id: member for member in config.members}
    env = build_council_env()
    participants: list[Participant] = []
    skipped: list[CouncilTurnState] = []
    for member_id in session.members:
        member = members_by_id.get(member_id)
        if member is None or not member.enabled:
            continue
        bin_path = resolve_backend_bin(member.backend, env)
        if bin_path is None:
            timestamp = deps.now()
            skipped.append(
                CouncilTurnState(
                    round=1, member_id=member_id, status=STATUS_SKIPPED,
                    started_at=timestamp, finished_at=timestamp, error=f"{member.backend} binary not found",
                )
            )
            continue
        participants.append(Participant(member=member, bin_path=bin_path, env=env))
    return participants, skipped


def _first_successful_responder(turns: list[CouncilTurnState], exclude: set[str]) -> str | None:
    for turn in turns:
        if turn.status == STATUS_DONE and turn.member_id not in exclude:
            return turn.member_id
    return None


def _record_title(topic: str) -> str:
    stripped = topic.strip()
    first_line = stripped.splitlines()[0].strip() if stripped else stripped
    if len(first_line) <= MAX_RECORD_TITLE_CHARS:
        return first_line
    return first_line[: MAX_RECORD_TITLE_CHARS - 1].rstrip() + TITLE_ELLIPSIS


def _record_body(synthesis_text: str, session: CouncilSession) -> str:
    source_lines = [
        SOURCE_SECTION_HEADER, "",
        f"- session: {session.id}",
        f"- members: {', '.join(session.members)}",
        f"- rounds: {session.rounds}",
        f"- thread: {session.thread}",
    ]
    return f"{synthesis_text.strip()}\n\n" + "\n".join(source_lines) + "\n"


def _record_payload(session: CouncilSession, synthesis_text: str) -> dict:
    return {
        "type": COUNCIL_RECORD_TYPE,
        "title": _record_title(session.topic),
        "project": session.project,
        "body": _record_body(synthesis_text, session),
        "tags": list(COUNCIL_RECORD_TAGS),
        "agent": COUNCIL_RECORD_AGENT,
        "session": session.id,
        "cwd": session.project_root,
    }


def _write_decision_record(session: CouncilSession, synthesis_text: str, deps: RunnerDeps) -> tuple[str | None, str | None]:
    payload = _record_payload(session, synthesis_text)
    try:
        record_id = deps.create_record(payload)
    except Exception as exc:
        return None, f"{RECORD_WRITE_FAILED_ERROR}: {exc}"
    if record_id is None:
        return None, RECORD_WRITE_FAILED_ERROR
    return record_id, None


def _dedupe_turns(turns: list[CouncilTurnState]) -> list[CouncilTurnState]:
    """Keep at most one turn per (round, member_id), newest write wins.

    Preserves the position of the first occurrence of each key so the turn
    order in session.json stays stable, while replacing its state with the
    latest one seen for that key.
    """
    order: list[tuple[int, str]] = []
    latest: dict[tuple[int, str], CouncilTurnState] = {}
    for turn in turns:
        key = (turn.round, turn.member_id)
        if key not in latest:
            order.append(key)
        latest[key] = turn
    return [latest[key] for key in order]


def _persist_turns(council_dir: Path, session: CouncilSession, new_turns: list[CouncilTurnState]) -> CouncilSession:
    if not new_turns:
        return session

    def _merge(current: CouncilSession) -> CouncilSession:
        if current.status == STATUS_CANCELLED:
            cancelled_turns = [turn for turn in new_turns if turn.status == STATUS_CANCELLED]
            if not cancelled_turns:
                return current
            return current.model_copy(update={"turns": _dedupe_turns(current.turns + cancelled_turns)})
        return current.model_copy(update={"turns": _dedupe_turns(current.turns + new_turns)})

    return update_session_with(council_dir, session.project, session.id, _merge)


def _mark_failed(session: CouncilSession, deps: RunnerDeps, error: str) -> CouncilSession:
    return session.model_copy(update={"status": STATUS_FAILED, "finished_at": deps.now(), "error": error})


def _is_cancelled(council_dir: Path, session: CouncilSession) -> bool:
    try:
        current = read_session(council_dir, session.project, session.id)
    except CouncilSessionError:
        return False
    return current.status == STATUS_CANCELLED


def _start_session(
    council_dir: Path, session: CouncilSession, runner_pid: int | None, runner_pgid: int | None
) -> CouncilSession:
    def _merge(current: CouncilSession) -> CouncilSession:
        if current.status == STATUS_CANCELLED:
            return current
        return current.model_copy(update={"status": "running", "runner_pid": runner_pid, "runner_pgid": runner_pgid})

    return update_session_with(council_dir, session.project, session.id, _merge)


def _finalize_session(council_dir: Path, session: CouncilSession) -> None:
    cleared = session.model_copy(update={"runner_pid": None, "runner_pgid": None})

    def _merge(current: CouncilSession) -> CouncilSession:
        return current if current.status == STATUS_CANCELLED else cleared

    update_session_with(council_dir, session.project, session.id, _merge)


def _refresh_round_memory(ctx: TurnContext) -> None:
    try:
        ctx.memory_lines = ctx.deps.search_memory(ctx.session.topic, ctx.session.project)
    except Exception:
        logger.warning("council memory search failed for session=%s", ctx.session.id, exc_info=True)
        ctx.memory_lines = []


def _mark_remaining_rounds_skipped(
    council_dir: Path, session: CouncilSession, participants: list[Participant], start_round: int, deps: RunnerDeps
) -> CouncilSession:
    timestamp = deps.now()
    skipped_turns = [
        CouncilTurnState(
            round=round_number, member_id=participant.member.id, status=STATUS_SKIPPED,
            started_at=timestamp, finished_at=timestamp, error=WALL_CLOCK_EXCEEDED_ERROR,
        )
        for round_number in range(start_round, session.rounds + 1)
        for participant in participants
    ]
    return _persist_turns(council_dir, session, skipped_turns)


def _run_synthesis(ctx: TurnContext, participants: list[Participant], session: CouncilSession) -> CouncilSession:
    ctx.session = session
    _refresh_round_memory(ctx)
    participants_by_id = {participant.member.id: participant for participant in participants}
    synth_round = RoundSpec(round_number=session.rounds + 1, kind=KIND_DECISION)

    primary_id = session.spokesperson if session.spokesperson in participants_by_id else None
    attempted: set[str] = set()
    synth_turn: CouncilTurnState | None = None

    if primary_id is not None:
        synth_turn = _run_single_turn_safe(ctx, participants_by_id[primary_id], synth_round)
        session = _persist_turns(ctx.council_dir, session, [synth_turn])
        attempted.add(primary_id)
        if session.status == STATUS_CANCELLED:
            return session

    if synth_turn is None or synth_turn.status != STATUS_DONE:
        fallback_id = _first_successful_responder(session.turns, attempted)
        if fallback_id is not None and fallback_id in participants_by_id:
            synth_turn = _run_single_turn_safe(ctx, participants_by_id[fallback_id], synth_round)
            session = _persist_turns(ctx.council_dir, session, [synth_turn])
            if session.status == STATUS_CANCELLED:
                return session

    if synth_turn is None or synth_turn.status != STATUS_DONE:
        return _mark_failed(session, ctx.deps, SYNTHESIS_FAILED_ERROR)

    synthesis_message = _find_message_by_id(ctx.council_dir, session.project, session.thread, synth_turn.message_id)
    synthesis_text = synthesis_message.body if synthesis_message is not None else ""
    if not synthesis_text.strip():
        return _mark_failed(session, ctx.deps, SYNTHESIS_EMPTY_ERROR)

    record_id, record_error = _write_decision_record(session, synthesis_text, ctx.deps)
    return session.model_copy(
        update={"status": "converged", "finished_at": ctx.deps.now(), "record_id": record_id, "error": record_error}
    )


def run_council_session(
    session: CouncilSession, config: CouncilConfig, council_dir: Path, deps: RunnerDeps,
    runner_pid: int | None = None, runner_pgid: int | None = None,
) -> CouncilSession:
    try:
        session = _start_session(council_dir, session, runner_pid, runner_pgid)
    except CouncilSessionError as exc:
        logger.exception("council: could not start session %s", session.id)
        return _mark_failed(session, deps, str(exc))
    if session.status == STATUS_CANCELLED:
        return session
    try:
        participants, skipped_turns = _build_participants(config, session, deps)
        session = _persist_turns(council_dir, session, skipped_turns)
        if session.status == STATUS_CANCELLED:
            return session

        if not participants:
            session = _mark_failed(session, deps, NO_AVAILABLE_MEMBERS_ERROR)
            return session

        ctx = TurnContext(config=config, council_dir=council_dir, session=session, deps=deps)

        for round_number in range(1, session.rounds + 1):
            if _is_cancelled(council_dir, session):
                return read_session(council_dir, session.project, session.id)

            if _seconds_elapsed(session.created_at, deps.now()) > MAX_SESSION_SECONDS:
                session = _mark_remaining_rounds_skipped(council_dir, session, participants, round_number, deps)
                if session.status == STATUS_CANCELLED:
                    return session
                if any(turn.status == STATUS_DONE for turn in session.turns):
                    session = _run_synthesis(ctx, participants, session)
                else:
                    session = _mark_failed(session, deps, WALL_CLOCK_EXCEEDED_ERROR)
                return session

            round_spec = RoundSpec(round_number=round_number, kind=_kind_for_round(round_number))
            ctx.session = session
            _refresh_round_memory(ctx)
            round_turns = (
                _run_round_parallel(ctx, participants, round_spec)
                if round_number == 1
                else _run_round_sequential(ctx, participants, round_spec)
            )
            session = _persist_turns(council_dir, session, round_turns)
            if session.status == STATUS_CANCELLED:
                return session
            if not any(turn.status == STATUS_DONE for turn in round_turns):
                session = _mark_failed(session, deps, f"round {round_number}: no member produced an answer")
                return session

        if _is_cancelled(council_dir, session):
            return read_session(council_dir, session.project, session.id)

        session = _run_synthesis(ctx, participants, session)
        return session
    except Exception as exc:
        session = _mark_failed(session, deps, str(exc))
        return session
    finally:
        try:
            _finalize_session(council_dir, session)
        except CouncilSessionError:
            logger.exception("council: could not finalize session %s", session.id)


def _default_spawn(request: SpawnRequest):
    log_handle = open(request.log_path, "w", encoding="utf-8")
    try:
        os.chmod(request.log_path, LOG_FILE_MODE)
    except OSError:
        logger.warning("council: could not chmod log file %s", request.log_path, exc_info=True)
    try:
        proc = subprocess.Popen(
            request.argv,
            executable=request.executable,
            cwd=request.cwd,
            env=request.env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    try:
        _register_active_pgid(os.getpgid(proc.pid))
    except ProcessLookupError:
        logger.warning("council: could not resolve pgid for freshly spawned pid=%s", proc.pid)
    return proc


def _format_search_result(result: dict) -> str:
    return f"- [{result.get('id')}] {result.get('title')} ({result.get('project')})"


def _default_search_memory(topic: str, project: str) -> list[str]:
    from persistent_memory.daemon.config import DAEMON_HOST, DAEMON_PORT

    url = f"http://{DAEMON_HOST}:{DAEMON_PORT}{COUNCIL_SEARCH_PATH}"
    try:
        response = httpx.get(url, params={"q": topic, "top_k": MEMORY_SEARCH_TOP_K}, timeout=SEARCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("council memory search failed for project=%s", project, exc_info=True)
        return []
    if not isinstance(data, dict):
        return []
    results = data.get("results", [])
    return [_format_search_result(result) for result in results if isinstance(result, dict)]


def _default_create_record(payload: dict, records_dir: Path) -> str | None:
    from persistent_memory.daemon.config import DAEMON_HOST, DAEMON_PORT
    from persistent_memory.daemon.token import read_token

    token = read_token(records_dir)
    if token is None:
        return None
    url = f"http://{DAEMON_HOST}:{DAEMON_PORT}/api/records"
    try:
        response = httpx.post(url, json=payload, headers={"X-PM-Token": token}, timeout=RECORD_WRITE_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return response.json().get("id")


def default_deps(records_dir: Path) -> RunnerDeps:
    return RunnerDeps(
        spawn=_default_spawn,
        now=_current_timestamp,
        search_memory=_default_search_memory,
        create_record=lambda payload: _default_create_record(payload, records_dir),
    )


def _cancel_running_session(council_dir: Path, project: str, session_id: str) -> None:
    _kill_all_active_process_groups()
    try:
        session = read_session(council_dir, project, session_id)
    except CouncilSessionError:
        logger.exception("council: cannot read session for cancellation: %s", session_id)
        return
    session = session.model_copy(
        update={
            "status": STATUS_CANCELLED, "finished_at": _current_timestamp(),
            "runner_pid": None, "runner_pgid": None,
        }
    )
    update_session(council_dir, session)


def _install_sigterm_handler(council_dir: Path, project: str, session_id: str) -> None:
    def _handle_sigterm(signum: int, frame: Any) -> None:
        logger.warning("council runner received SIGTERM for session=%s; cancelling", session_id)
        _cancel_running_session(council_dir, project, session_id)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m persistent_memory.council.runner")
    parser.add_argument("--records-dir", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from persistent_memory.daemon.config import DaemonConfig

    args = _parse_args(argv)
    records_dir = Path(args.records_dir)
    council_dir = DaemonConfig(records_dir=records_dir).council_dir

    try:
        session = read_session(council_dir, args.project, args.session)
    except CouncilSessionError:
        logger.exception("council session not found: project=%s session=%s", args.project, args.session)
        return 1

    try:
        config, _source = load_council_config(Path(session.project_root))
    except CouncilConfigError as exc:
        session = session.model_copy(update={"status": STATUS_FAILED, "error": str(exc)})
        update_session(council_dir, session)
        return 1

    _install_sigterm_handler(council_dir, args.project, args.session)
    runner_pid = os.getpid()
    runner_pgid = os.getpgid(0)
    run_council_session(
        session, config, council_dir, default_deps(records_dir), runner_pid=runner_pid, runner_pgid=runner_pgid
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
