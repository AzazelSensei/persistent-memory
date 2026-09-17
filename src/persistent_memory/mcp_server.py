"""MCP server — a thin stdio wrapper over the running daemon's HTTP API.

Lets an agent ACTIVELY query memory (search/get/list/provenance) and create
manual records when something must be captured immediately. It complements the
passive recall/extraction done by the hooks. Reuses the daemon's loaded index
(the embedding model is not loaded a second time).

Run (from a Claude Code / Codex MCP config):
    <venv>/bin/python -m persistent_memory.mcp_server
"""

import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

DAEMON_BASE_URL = os.environ.get("PM_DAEMON_URL", "http://127.0.0.1:37778")
TOKEN_HEADER = "X-PM-Token"
HTTP_TIMEOUT_SECONDS = 5.0
DEFAULT_TOP_K = 5
DEFAULT_RECENT_LIMIT = 10
DAEMON_DOWN_MSG = (
    "persistent-memory daemon is not responding (127.0.0.1:37778). "
    "Check it with `python -m persistent_memory.doctor` or install.sh."
)
TOKEN_REJECTED_MSG = "persistent-memory daemon rejected the local token."
DAEMON_ERROR_MSG_TEMPLATE = "persistent-memory daemon returned an error (status {status})."
DAEMON_REJECTED_REQUEST_MSG_TEMPLATE = "persistent-memory daemon rejected the request (status {status}): {detail}"

COUNCIL_READONLY_ENV = "PM_COUNCIL_READONLY"
COUNCIL_READONLY_BLOCK_MSG = (
    "Blocked: this session runs as a council member; your answer is captured from "
    "your output. Do not post to the board or create records."
)


def _is_council_readonly() -> bool:
    return os.environ.get(COUNCIL_READONLY_ENV) == "1"


mcp = FastMCP("persistent-memory")


class TokenError(RuntimeError):
    pass


def _get(path: str, params: dict | None = None) -> dict:
    response = httpx.get(
        f"{DAEMON_BASE_URL}{path}", params=params or {}, timeout=HTTP_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


def _daemon_token() -> str:
    health = _get("/api/health")
    records_dir = health.get("records_dir")
    if not records_dir:
        raise TokenError("daemon health response did not include records_dir")
    token_path = Path(records_dir) / ".pm-index" / "daemon.token"
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TokenError(f"could not read daemon token at {token_path}") from exc
    if not token:
        raise TokenError(f"daemon token is empty at {token_path}")
    return token


def _format_validation_detail(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            msg = item.get("msg", "")
            loc = item.get("loc")
            if isinstance(loc, (list, tuple)) and loc:
                loc_str = ".".join(str(part) for part in loc)
                parts.append(f"{loc_str}: {msg}" if msg else loc_str)
            else:
                parts.append(msg or str(item))
        return "; ".join(parts)
    return str(detail)


def _response_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict) and "detail" in data:
        return _format_validation_detail(data["detail"])
    return _format_validation_detail(data)


def _describe_http_status_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status == 403:
        return TOKEN_REJECTED_MSG
    if status >= 500:
        return DAEMON_ERROR_MSG_TEMPLATE.format(status=status)
    detail = _response_error_detail(exc.response)
    return DAEMON_REJECTED_REQUEST_MSG_TEMPLATE.format(status=status, detail=detail)


def _post(path: str, payload: dict) -> dict:
    response = httpx.post(
        f"{DAEMON_BASE_URL}{path}",
        json=payload,
        headers={TOKEN_HEADER: _daemon_token()},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


@mcp.tool()
def search_memory(query: str, top_k: int = DEFAULT_TOP_K) -> str:
    """Retrieve past DECISIONS (D-####) and LESSONS (L-####) via hybrid semantic + keyword search (all projects).

    Use when: during a task you wonder "what did we decide / learn about this before",
    or when the recall block injected at session start is not enough.
    query: topic to search for (e.g. "database choice", "extraction cost", "auth bug").
    top_k: number of results (default 5).
    Each returned line: [ID] title (project) — score. Use get_record(ID) for the full content.
    """
    try:
        data = _get("/api/search", {"q": query, "top_k": top_k})
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    results = data.get("results", [])
    if not results:
        return f"No results for '{query}'."
    lines = [
        f"- [{r.get('id')}] {r.get('title') or ''} ({r.get('project') or ''}) "
        f"— score {round(float(r.get('score') or 0.0), 3)}"
        for r in results
    ]
    return "\n".join(lines)


@mcp.tool()
def get_record(record_id: str) -> str:
    """Fetch the FULL markdown body of a record (Context/Decision/Rationale/Outcome + source quote).

    record_id: e.g. "D-0042" (decision) or "L-0017" (lesson).
    """
    try:
        data = _get(f"/api/records/{record_id}/raw")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 422):
            return f"Record not found: {record_id}"
        return DAEMON_DOWN_MSG
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    return data.get("body") or f"Empty record: {record_id}"


@mcp.tool()
def list_recent(record_type: str | None = None, limit: int = DEFAULT_RECENT_LIMIT) -> str:
    """List the most recently recorded decisions/lessons (by date, newest -> oldest).

    record_type: "decision" | "lesson" | None (all).
    limit: number of records (default 10).
    """
    params: dict = {"titles": "true"}
    if record_type:
        params["type"] = record_type
    try:
        data = _get("/api/records", params)
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    records = sorted(
        data.get("records", []), key=lambda r: str(r.get("date") or ""), reverse=True
    )[:limit]
    if not records:
        return "No records."
    return "\n".join(
        f"- [{r.get('id')}] {r.get('title') or ''} "
        f"({r.get('project') or ''}, {r.get('date') or ''}, {r.get('status') or ''})"
        for r in records
    )


@mcp.tool()
def get_record_provenance(record_id: str) -> str:
    """Fetch the ORIGINAL transcript quotes a record is based on (reason-preserving / auditable source).

    Use when: you want to verify what a decision was actually based on.
    record_id: e.g. "D-0042".
    """
    try:
        data = _get(f"/api/records/{record_id}/source")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 422):
            return f"Record not found: {record_id}"
        return DAEMON_DOWN_MSG
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    passages = data.get("passages", [])
    if not passages:
        return f"No source quotes for {record_id}."
    return "\n\n".join(
        f"[{p.get('time') or ''}] (score {p.get('score')})\n{p.get('text') or ''}"
        for p in passages
    )


@mcp.tool()
def create_record(
    record_type: str,
    title: str,
    project: str,
    body: str | None = None,
    tags: list[str] | None = None,
    salience: float = 0.5,
    session: str | None = None,
    cwd: str | None = None,
    agent: str | None = "mcp",
    branch: str | None = None,
) -> str:
    """Create a proposed decision or lesson record immediately.

    Use for "record this now" moments when waiting for automatic extraction is
    undesirable. The daemon still enforces its local X-PM-Token write guard; this
    tool discovers the records_dir via /api/health and reads the daemon token
    from records_dir/.pm-index/daemon.token.

    record_type: "decision" or "lesson".
    title: human-readable record title.
    project: project/category name to store in frontmatter.
    body: optional markdown body using canonical headings; omit to use the template.
    tags: optional list of tags.
    salience: optional 0-1 importance score, default 0.5.
    session/cwd/agent/branch: optional provenance fields.
    """
    if _is_council_readonly():
        return COUNCIL_READONLY_BLOCK_MSG

    payload: dict = {
        "type": record_type,
        "title": title,
        "project": project,
        "salience": salience,
    }
    if body is not None:
        payload["body"] = body
    if tags is not None:
        payload["tags"] = tags
    if session is not None:
        payload["session"] = session
    if cwd is not None:
        payload["cwd"] = cwd
    if agent is not None:
        payload["agent"] = agent
    if branch is not None:
        payload["branch"] = branch

    try:
        data = _post("/api/records", payload)
    except TokenError as exc:
        return f"persistent-memory MCP could not read the daemon token: {exc}"
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            try:
                detail = exc.response.json().get("detail")
            except ValueError:
                detail = exc.response.text
            return f"Invalid record payload: {detail or exc.response.text}"
        if exc.response.status_code == 403:
            return "persistent-memory daemon rejected the local token."
        return DAEMON_DOWN_MSG
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG

    return (
        f"Created {data.get('type') or record_type} record "
        f"{data.get('id') or ''} at {data.get('path') or ''}."
    ).strip()


COUNCIL_BOARD_PATH = "/api/council/board"
COUNCIL_THREADS_PATH = "/api/council/threads"
DEFAULT_COUNCIL_THREAD = "general"
DEFAULT_COUNCIL_KIND = "note"
DEFAULT_COUNCIL_AUTHOR = "agent"
DEFAULT_COUNCIL_READ_LIMIT = 20
COUNCIL_BODY_PREVIEW_CHARS = 200
NO_COUNCIL_MESSAGES_MSG = "No messages."
NO_COUNCIL_THREADS_MSG = "No threads."
COUNCIL_VIA = "mcp"
COUNCIL_TIME_SLICE_START = 11
COUNCIL_TIME_SLICE_END = 16


def _split_refs(refs: str | None) -> list[str]:
    if not refs:
        return []
    return [item.strip() for item in refs.split(",") if item.strip()]


def _council_message_time(ts: str) -> str:
    if len(ts) < COUNCIL_TIME_SLICE_END:
        return ts
    return ts[COUNCIL_TIME_SLICE_START:COUNCIL_TIME_SLICE_END]


@mcp.tool()
def council_post(
    body: str,
    project: str,
    thread: str = DEFAULT_COUNCIL_THREAD,
    kind: str = DEFAULT_COUNCIL_KIND,
    role: str | None = None,
    refs: str | None = None,
    author: str = DEFAULT_COUNCIL_AUTHOR,
) -> str:
    """Post a message to a project's AI Council board — a shared, append-only
    channel that other AI CLIs (Claude, Codex, Kimi, Grok) working on the same
    project can read, even across separate sessions.

    Use when: you just finished something other agents should know about, you
    want to leave a note/question/critique for whoever picks up the project
    next, or you are participating in a guided council deliberation thread.
    body: the message text.
    project: project/category name (same one used for records).
    thread: "general" for free-form chat, or a council session thread id (e.g. "c-0007").
    kind: "note" | "proposal" | "critique" | "vote" | "decision" | "handoff" | "question".
    role: optional short role label for this message (e.g. "Implementer").
    refs: optional comma-separated record ids this message references (e.g. "D-0215,L-0546").
    author: who is posting; pass your own identity (e.g. "codex", "grok"). Defaults to "agent".
    """
    if _is_council_readonly():
        return COUNCIL_READONLY_BLOCK_MSG

    payload = {
        "project": project,
        "body": body,
        "thread": thread,
        "kind": kind,
        "author": author,
        "via": COUNCIL_VIA,
        "role": role,
        "refs": _split_refs(refs),
    }
    try:
        data = _post(COUNCIL_BOARD_PATH, payload)
    except TokenError as exc:
        return f"persistent-memory MCP could not read the daemon token: {exc}"
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            return f"Invalid council message: {_response_error_detail(exc.response)}"
        return _describe_http_status_error(exc)
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG

    return f"Posted {data.get('id') or ''} to thread {data.get('thread') or thread}"


@mcp.tool()
def council_read(
    project: str,
    thread: str | None = None,
    since: str | None = None,
    limit: int = DEFAULT_COUNCIL_READ_LIMIT,
) -> str:
    """Read recent messages from a project's AI Council board.

    Use when: you want to catch up on what other agents (or an ongoing council
    deliberation) posted before continuing work, or check for replies since
    your last read.
    project: project/category name.
    thread: "general" for free-form chat, or a council session thread id (e.g. "c-0007"); omit for all threads.
    since: only return messages with id greater than this (e.g. "m-0010"), for incremental reads.
    limit: max messages to return (default 20).
    Each returned line: [id] HH:MM author (kind, thread=...): body preview.
    """
    params: dict = {"project": project, "limit": limit}
    if thread is not None:
        params["thread"] = thread
    if since is not None:
        params["since"] = since
    try:
        data = _get(COUNCIL_BOARD_PATH, params)
    except httpx.HTTPStatusError as exc:
        return _describe_http_status_error(exc)
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG

    messages = data.get("messages", [])
    if not messages:
        return NO_COUNCIL_MESSAGES_MSG
    lines = [
        f"[{message.get('id')}] {_council_message_time(message.get('ts') or '')} "
        f"{message.get('author')} ({message.get('kind')}, thread={message.get('thread')}): "
        f"{(message.get('body') or '')[:COUNCIL_BODY_PREVIEW_CHARS]}"
        for message in messages
    ]
    return "\n".join(lines)


@mcp.tool()
def council_threads(project: str) -> str:
    """List the discussion threads on a project's AI Council board.

    Use when: you want an overview of ongoing conversations/deliberations
    before diving into one with council_read, or want to see who is active.
    project: project/category name.
    Each returned line: thread — message count, last activity time, participants.
    """
    try:
        data = _get(COUNCIL_THREADS_PATH, {"project": project})
    except httpx.HTTPStatusError as exc:
        return _describe_http_status_error(exc)
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG

    threads = data.get("threads", [])
    if not threads:
        return NO_COUNCIL_THREADS_MSG
    lines = [
        f"{t.get('thread')} — {t.get('count')} messages, last: {_council_message_time(t.get('last_ts') or '')}, "
        f"participants: {', '.join(t.get('authors') or [])}"
        for t in threads
    ]
    return "\n".join(lines)


COUNCIL_SESSIONS_PATH = "/api/council/sessions"
NO_COUNCIL_SESSIONS_MSG_TEMPLATE = "No council sessions for {project}."
COUNCIL_SESSION_NOT_FOUND_MSG_TEMPLATE = "Council session not found: {session_id}"
COUNCIL_SESSION_ACTIVE_MSG_TEMPLATE = "A council session is already active for {project}: {detail}"
COUNCIL_SESSION_INVALID_MSG_TEMPLATE = "Invalid council session request: {detail}"
COUNCIL_STATUS_WATCH_HINT_TEMPLATE = 'Watch: council_status(project="{project}", session_id="{session_id}")'


@mcp.tool()
def council_open(project: str, topic: str, cwd: str, rounds: int | None = None) -> str:
    """Open a new AI Council deliberation: several AI CLIs (Claude, Codex, Grok)
    debate one topic over a fixed number of rounds and a spokesperson synthesises
    a decision back into persistent memory as a proposed D-#### record.

    Use when: a human asks you to convene the council / get a second opinion from
    the other models on a real decision for this project.
    project: project/category name (same one used for records and the board).
    topic: the question the council should decide.
    cwd: absolute path to the project's working directory (used to load
    `.pm-council.yaml` and to run each member's CLI in the right repo).
    rounds: optional round count override; the project config sets the default
    and caps.
    Only one council session may run per project at a time; starting a second
    one while another is pending/running returns the id of the existing session.
    """
    payload: dict = {"project": project, "topic": topic, "cwd": cwd}
    if rounds is not None:
        payload["rounds"] = rounds

    try:
        data = _post(COUNCIL_SESSIONS_PATH, payload)
    except TokenError as exc:
        return f"persistent-memory MCP could not read the daemon token: {exc}"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 409:
            return COUNCIL_SESSION_ACTIVE_MSG_TEMPLATE.format(
                project=project, detail=_response_error_detail(exc.response)
            )
        if status == 422:
            return COUNCIL_SESSION_INVALID_MSG_TEMPLATE.format(detail=_response_error_detail(exc.response))
        return _describe_http_status_error(exc)
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG

    session_id = data.get("id") or ""
    members = data.get("members") or []
    estimated_calls = data.get("estimated_calls")
    return (
        f"Council session {session_id} started with {len(members)} members "
        f"({estimated_calls} calls). "
        + COUNCIL_STATUS_WATCH_HINT_TEMPLATE.format(project=project, session_id=session_id)
    )


def _format_council_turns(turns: list[dict]) -> list[str]:
    turns_by_round: dict[int, list[dict]] = {}
    for turn in turns:
        turns_by_round.setdefault(turn.get("round"), []).append(turn)
    lines = []
    for round_number in sorted(turns_by_round):
        parts = [f"{turn.get('member_id')}:{turn.get('status')}" for turn in turns_by_round[round_number]]
        lines.append(f"round {round_number}: " + ", ".join(parts))
    return lines


def _format_council_status(session: dict) -> str:
    lines = [f"{session.get('id')} ({session.get('status')}) — {session.get('topic')}"]
    lines.extend(_format_council_turns(session.get("turns") or []))
    if session.get("record_id"):
        lines.append(f"record: {session.get('record_id')}")
    if session.get("error"):
        lines.append(f"error: {session.get('error')}")
    return "\n".join(lines)


@mcp.tool()
def council_status(project: str, session_id: str | None = None) -> str:
    """Check the progress of an AI Council deliberation.

    Use when: you started a council with council_open and want to know whether
    it converged, which members answered each round, and whether a decision
    record was written.
    project: project/category name.
    session_id: e.g. "c-0007"; omit to check the most recent session for the project.
    Returns: session id and status, one line per round showing each member's
    turn status (done/failed/timeout/skipped), and the resulting record id if any.
    """
    try:
        if session_id is None:
            listing = _get(COUNCIL_SESSIONS_PATH, {"project": project, "limit": 1})
            sessions = listing.get("sessions", [])
            if not sessions:
                return NO_COUNCIL_SESSIONS_MSG_TEMPLATE.format(project=project)
            session_id = sessions[0].get("id")
        detail = _get(f"{COUNCIL_SESSIONS_PATH}/{session_id}", {"project": project})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return COUNCIL_SESSION_NOT_FOUND_MSG_TEMPLATE.format(session_id=session_id)
        return _describe_http_status_error(exc)
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG

    return _format_council_status(detail)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
