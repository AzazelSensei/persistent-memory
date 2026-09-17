import httpx

from persistent_memory import mcp_server


def test_daemon_token_reads_token_from_health_records_dir(tmp_path, monkeypatch):
    token_dir = tmp_path / ".pm-index"
    token_dir.mkdir()
    (token_dir / "daemon.token").write_text("secret-token\n", encoding="utf-8")

    def fake_get(path, params=None):
        assert path == "/api/health"
        return {"records_dir": str(tmp_path)}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    assert mcp_server._daemon_token() == "secret-token"


def test_create_record_posts_daemon_payload(monkeypatch):
    seen = {}

    def fake_post(path, payload):
        seen["path"] = path
        seen["payload"] = payload
        return {"id": "L-0001", "path": "/tmp/lessons/L-0001.md", "type": "lesson"}

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.create_record(
        record_type="lesson",
        title="MCP writes records",
        project="persistent-memory",
        body="## What happened\n\nCodex needed a direct write tool.",
        tags=["mcp", "codex"],
        salience=0.8,
        session="S1",
        cwd="/repo",
        agent="codex",
        branch="main",
    )

    assert seen["path"] == "/api/records"
    assert seen["payload"] == {
        "type": "lesson",
        "title": "MCP writes records",
        "project": "persistent-memory",
        "body": "## What happened\n\nCodex needed a direct write tool.",
        "tags": ["mcp", "codex"],
        "salience": 0.8,
        "session": "S1",
        "cwd": "/repo",
        "agent": "codex",
        "branch": "main",
    }
    assert result == "Created lesson record L-0001 at /tmp/lessons/L-0001.md."


def test_create_record_reports_validation_error(monkeypatch):
    request = httpx.Request("POST", "http://test/api/records")
    response = httpx.Response(
        status_code=422,
        json={"detail": "invalid type 'principle': must be 'decision' or 'lesson'"},
        request=request,
    )

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.create_record(
        record_type="principle", title="Bad", project="persistent-memory"
    )

    assert result == (
        "Invalid record payload: invalid type 'principle': must be 'decision' or 'lesson'"
    )


def test_council_post_sends_daemon_payload(monkeypatch):
    seen = {}

    def fake_post(path, payload):
        seen["path"] = path
        seen["payload"] = payload
        return {"id": "m-0003", "thread": "general", "ts": "2026-07-24T22:41:03Z"}

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(
        body="Extraction argv fixed for kimi.",
        project="persistent-memory",
        thread="general",
        kind="note",
        role="Uygulayici",
        refs="D-0215, L-0546",
        author="codex",
    )

    assert seen["path"] == "/api/council/board"
    assert seen["payload"] == {
        "project": "persistent-memory",
        "body": "Extraction argv fixed for kimi.",
        "thread": "general",
        "kind": "note",
        "author": "codex",
        "via": "mcp",
        "role": "Uygulayici",
        "refs": ["D-0215", "L-0546"],
    }
    assert result == "Posted m-0003 to thread general"


def test_council_post_defaults_author_and_refs(monkeypatch):
    seen = {}

    def fake_post(path, payload):
        seen["payload"] = payload
        return {"id": "m-0001", "thread": "general", "ts": "2026-07-24T22:41:03Z"}

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    mcp_server.council_post(body="hello", project="persistent-memory")

    assert seen["payload"]["author"] == "agent"
    assert seen["payload"]["refs"] == []
    assert seen["payload"]["via"] == "mcp"


def test_council_post_daemon_down(monkeypatch):
    def fake_post(path, payload):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(body="hello", project="persistent-memory")

    assert result == mcp_server.DAEMON_DOWN_MSG


def test_council_post_reports_validation_error(monkeypatch):
    request = httpx.Request("POST", "http://test/api/council/board")
    response = httpx.Response(
        status_code=422,
        json={"detail": "body must not be empty"},
        request=request,
    )

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(body="", project="persistent-memory")

    assert result == "Invalid council message: body must not be empty"


def test_council_read_formats_messages(monkeypatch):
    def fake_get(path, params=None):
        assert path == "/api/council/board"
        assert params == {"project": "persistent-memory", "limit": 20, "thread": "general"}
        return {
            "project": "persistent-memory",
            "thread": "general",
            "messages": [
                {
                    "id": "m-0003",
                    "ts": "2026-07-24T22:41:03Z",
                    "project": "persistent-memory",
                    "thread": "general",
                    "author": "codex",
                    "kind": "critique",
                    "body": "x" * 250,
                    "via": "http",
                    "role": None,
                    "turn": None,
                    "refs": [],
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="persistent-memory", thread="general")

    assert result == (
        f"[m-0003] 22:41 codex (critique, thread=general): {'x' * 200}"
    )


def test_council_read_empty_result(monkeypatch):
    def fake_get(path, params=None):
        return {"project": "persistent-memory", "thread": None, "messages": [], "count": 0}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="persistent-memory")

    assert result == "No messages."


def test_council_read_daemon_down(monkeypatch):
    def fake_get(path, params=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="persistent-memory")

    assert result == mcp_server.DAEMON_DOWN_MSG


def test_council_threads_formats_summary(monkeypatch):
    def fake_get(path, params=None):
        assert path == "/api/council/threads"
        assert params == {"project": "persistent-memory"}
        return {
            "project": "persistent-memory",
            "threads": [
                {
                    "thread": "general",
                    "count": 12,
                    "last_ts": "2026-07-24T22:41:03Z",
                    "authors": ["codex", "grok"],
                }
            ],
        }

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_threads(project="persistent-memory")

    assert result == "general — 12 messages, last: 22:41, participants: codex, grok"


def test_council_threads_empty_result(monkeypatch):
    def fake_get(path, params=None):
        return {"project": "persistent-memory", "threads": []}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_threads(project="persistent-memory")

    assert result == "No threads."


def test_council_threads_daemon_down(monkeypatch):
    def fake_get(path, params=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_threads(project="persistent-memory")

    assert result == mcp_server.DAEMON_DOWN_MSG


def test_council_threads_reports_bad_status(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/threads")
    response = httpx.Response(status_code=500, request=request)

    def fake_get(path, params=None):
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_threads(project="persistent-memory")

    assert result == "persistent-memory daemon returned an error (status 500)."


def test_council_threads_reports_token_rejection(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/threads")
    response = httpx.Response(status_code=403, request=request)

    def fake_get(path, params=None):
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_threads(project="persistent-memory")

    assert result == mcp_server.TOKEN_REJECTED_MSG


def test_council_read_reports_token_rejection(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/board")
    response = httpx.Response(status_code=403, request=request)

    def fake_get(path, params=None):
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="persistent-memory")

    assert result == mcp_server.TOKEN_REJECTED_MSG


def test_council_read_reports_bad_status(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/board")
    response = httpx.Response(status_code=503, request=request)

    def fake_get(path, params=None):
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="persistent-memory")

    assert result == "persistent-memory daemon returned an error (status 503)."


def test_council_post_reports_token_rejection(monkeypatch):
    request = httpx.Request("POST", "http://test/api/council/board")
    response = httpx.Response(status_code=403, request=request)

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(body="hello", project="persistent-memory")

    assert result == mcp_server.TOKEN_REJECTED_MSG


def test_council_post_reports_bad_status(monkeypatch):
    request = httpx.Request("POST", "http://test/api/council/board")
    response = httpx.Response(status_code=502, request=request)

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(body="hello", project="persistent-memory")

    assert result == "persistent-memory daemon returned an error (status 502)."


def test_council_read_reports_422_with_detail_not_daemon_down(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/board")
    response = httpx.Response(
        status_code=422,
        json={"detail": "invalid since id: 'zzz'"},
        request=request,
    )

    def fake_get(path, params=None):
        raise httpx.HTTPStatusError("unprocessable", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="persistent-memory", since="zzz")

    assert result != mcp_server.DAEMON_DOWN_MSG
    assert "invalid since id: 'zzz'" in result


def test_council_read_reports_422_formats_fastapi_list_detail(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/board")
    response = httpx.Response(
        status_code=422,
        json={
            "detail": [
                {"loc": ["query", "limit"], "msg": "Input should be less than or equal to 500", "type": "less_than_equal"}
            ]
        },
        request=request,
    )

    def fake_get(path, params=None):
        raise httpx.HTTPStatusError("unprocessable", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="persistent-memory", limit=1000)

    assert result != mcp_server.DAEMON_DOWN_MSG
    assert "limit" in result
    assert "Input should be less than or equal to 500" in result
    assert "{'loc'" not in result
    assert "[{" not in result


def test_council_threads_reports_422_with_detail_not_daemon_down(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/threads")
    response = httpx.Response(
        status_code=422,
        json={"detail": "project is required"},
        request=request,
    )

    def fake_get(path, params=None):
        raise httpx.HTTPStatusError("unprocessable", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_threads(project="persistent-memory")

    assert result != mcp_server.DAEMON_DOWN_MSG
    assert "project is required" in result


def test_council_post_reports_422_formats_fastapi_list_detail(monkeypatch):
    request = httpx.Request("POST", "http://test/api/council/board")
    response = httpx.Response(
        status_code=422,
        json={
            "detail": [
                {"loc": ["body", "author"], "msg": "String should have at most 64 characters", "type": "string_too_long"}
            ]
        },
        request=request,
    )

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("unprocessable", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(body="hello", project="persistent-memory", author="a" * 65)

    assert result != mcp_server.DAEMON_DOWN_MSG
    assert "author" in result
    assert "String should have at most 64 characters" in result
    assert "{'loc'" not in result


# ---------------------------------------------------------------------------
# council_open
# ---------------------------------------------------------------------------

def test_council_open_sends_daemon_payload(monkeypatch):
    seen = {}

    def fake_post(path, payload):
        seen["path"] = path
        seen["payload"] = payload
        return {
            "id": "c-0001",
            "project": "persistent-memory",
            "thread": "c-0001",
            "members": ["claude", "codex", "grok"],
            "rounds": 2,
            "estimated_calls": 7,
            "log_dir": "/tmp/council-logs",
        }

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_open(
        project="persistent-memory", topic="should we ship X?", cwd="/repo"
    )

    assert seen["path"] == "/api/council/sessions"
    assert seen["payload"] == {"project": "persistent-memory", "topic": "should we ship X?", "cwd": "/repo"}
    assert result == (
        "Council session c-0001 started with 3 members (7 calls). "
        'Watch: council_status(project="persistent-memory", session_id="c-0001")'
    )


def test_council_open_passes_rounds_override(monkeypatch):
    seen = {}

    def fake_post(path, payload):
        seen["payload"] = payload
        return {"id": "c-0002", "members": ["claude"], "estimated_calls": 4}

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    mcp_server.council_open(project="persistent-memory", topic="x", cwd="/repo", rounds=3)

    assert seen["payload"]["rounds"] == 3


def test_council_open_daemon_down(monkeypatch):
    def fake_post(path, payload):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_open(project="persistent-memory", topic="x", cwd="/repo")

    assert result == mcp_server.DAEMON_DOWN_MSG


def test_council_open_active_session_returns_existing_id(monkeypatch):
    request = httpx.Request("POST", "http://test/api/council/sessions")
    response = httpx.Response(
        status_code=409,
        json={"detail": "project already has an active council session: c-0003"},
        request=request,
    )

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("conflict", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_open(project="persistent-memory", topic="x", cwd="/repo")

    assert "already active" in result
    assert "c-0003" in result


def test_council_open_reports_validation_error(monkeypatch):
    request = httpx.Request("POST", "http://test/api/council/sessions")
    response = httpx.Response(
        status_code=422,
        json={"detail": "cwd must be an absolute path"},
        request=request,
    )

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_open(project="persistent-memory", topic="x", cwd="repo")

    assert result == "Invalid council session request: cwd must be an absolute path"


def test_council_open_reports_token_rejection(monkeypatch):
    request = httpx.Request("POST", "http://test/api/council/sessions")
    response = httpx.Response(status_code=403, json={"detail": "forbidden"}, request=request)

    def fake_post(path, payload):
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_open(project="persistent-memory", topic="x", cwd="/repo")

    assert result == mcp_server.TOKEN_REJECTED_MSG


# ---------------------------------------------------------------------------
# council_status
# ---------------------------------------------------------------------------

def test_council_status_with_explicit_session_id(monkeypatch):
    def fake_get(path, params=None):
        assert path == "/api/council/sessions/c-0001"
        assert params == {"project": "persistent-memory"}
        return {
            "id": "c-0001",
            "status": "running",
            "topic": "should we ship X?",
            "turns": [
                {"round": 1, "member_id": "claude", "status": "done"},
                {"round": 1, "member_id": "codex", "status": "failed"},
            ],
            "record_id": None,
            "error": None,
        }

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_status(project="persistent-memory", session_id="c-0001")

    assert result == (
        "c-0001 (running) — should we ship X?\n"
        "round 1: claude:done, codex:failed"
    )


def test_council_status_defaults_to_most_recent_session(monkeypatch):
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params))
        if path == "/api/council/sessions":
            assert params == {"project": "persistent-memory", "limit": 1}
            return {"project": "persistent-memory", "sessions": [{"id": "c-0005"}]}
        assert path == "/api/council/sessions/c-0005"
        return {"id": "c-0005", "status": "converged", "topic": "x", "turns": [], "record_id": "D-0300"}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_status(project="persistent-memory")

    assert calls[0][0] == "/api/council/sessions"
    assert result == "c-0005 (converged) — x\nrecord: D-0300"


def test_council_status_no_sessions_for_project(monkeypatch):
    def fake_get(path, params=None):
        return {"project": "persistent-memory", "sessions": []}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_status(project="persistent-memory")

    assert result == "No council sessions for persistent-memory."


def test_council_status_session_not_found(monkeypatch):
    request = httpx.Request("GET", "http://test/api/council/sessions/c-9999")
    response = httpx.Response(status_code=404, json={"detail": "session not found: c-9999"}, request=request)

    def fake_get(path, params=None):
        if path == "/api/council/sessions":
            return {"sessions": [{"id": "c-9999"}]}
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_status(project="persistent-memory")

    assert result == "Council session not found: c-9999"


def test_council_status_daemon_down(monkeypatch):
    def fake_get(path, params=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_status(project="persistent-memory", session_id="c-0001")

    assert result == mcp_server.DAEMON_DOWN_MSG


# ---------------------------------------------------------------------------
# MUST-FIX 5 — write tools are blocked when PM_COUNCIL_READONLY=1 (a council
# member's own MCP session); read tools are never affected
# ---------------------------------------------------------------------------


def test_council_post_blocked_when_readonly_env_flag_set(monkeypatch):
    monkeypatch.setenv(mcp_server.COUNCIL_READONLY_ENV, "1")

    def fake_post(path, payload):
        raise AssertionError("council_post must not reach the daemon when read-only")

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(body="hello", project="persistent-memory")

    assert result == mcp_server.COUNCIL_READONLY_BLOCK_MSG


def test_council_post_allowed_when_readonly_env_flag_absent(monkeypatch):
    monkeypatch.delenv(mcp_server.COUNCIL_READONLY_ENV, raising=False)

    def fake_post(path, payload):
        return {"id": "m-0001", "thread": "general"}

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.council_post(body="hello", project="persistent-memory")

    assert result == "Posted m-0001 to thread general"


def test_create_record_blocked_when_readonly_env_flag_set(monkeypatch):
    monkeypatch.setenv(mcp_server.COUNCIL_READONLY_ENV, "1")

    def fake_post(path, payload):
        raise AssertionError("create_record must not reach the daemon when read-only")

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.create_record(record_type="decision", title="t", project="p")

    assert result == mcp_server.COUNCIL_READONLY_BLOCK_MSG


def test_create_record_allowed_when_readonly_env_flag_absent(monkeypatch):
    monkeypatch.delenv(mcp_server.COUNCIL_READONLY_ENV, raising=False)

    def fake_post(path, payload):
        return {"id": "D-0001", "path": "/tmp/D-0001.md", "type": "decision"}

    monkeypatch.setattr(mcp_server, "_post", fake_post)

    result = mcp_server.create_record(record_type="decision", title="t", project="p")

    assert result == "Created decision record D-0001 at /tmp/D-0001.md."


def test_council_read_not_blocked_by_readonly_env_flag(monkeypatch):
    monkeypatch.setenv(mcp_server.COUNCIL_READONLY_ENV, "1")

    def fake_get(path, params=None):
        return {"project": "p", "thread": None, "messages": [], "count": 0}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_read(project="p")

    assert result == "No messages."


def test_council_threads_not_blocked_by_readonly_env_flag(monkeypatch):
    monkeypatch.setenv(mcp_server.COUNCIL_READONLY_ENV, "1")

    def fake_get(path, params=None):
        return {"project": "p", "threads": []}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_threads(project="p")

    assert result == "No threads."


def test_search_memory_not_blocked_by_readonly_env_flag(monkeypatch):
    monkeypatch.setenv(mcp_server.COUNCIL_READONLY_ENV, "1")

    def fake_get(path, params=None):
        return {"results": []}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.search_memory("q")

    assert result == "No results for 'q'."


def test_get_record_not_blocked_by_readonly_env_flag(monkeypatch):
    monkeypatch.setenv(mcp_server.COUNCIL_READONLY_ENV, "1")

    def fake_get(path, params=None):
        return {"body": "the record body"}

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.get_record("D-0001")

    assert result == "the record body"


def test_council_status_shows_error_field(monkeypatch):
    def fake_get(path, params=None):
        return {
            "id": "c-0002",
            "status": "failed",
            "topic": "x",
            "turns": [],
            "record_id": None,
            "error": "no council member is available (all skipped or unresolved)",
        }

    monkeypatch.setattr(mcp_server, "_get", fake_get)

    result = mcp_server.council_status(project="persistent-memory", session_id="c-0002")

    assert "error: no council member is available" in result
