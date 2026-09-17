"""Tests for the AI Council board HTTP endpoints."""

import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from persistent_memory.council.config import CONFIG_FILENAME, MAX_CONFIG_BYTES, MAX_MEMBERS, MAX_ROUNDS
from persistent_memory.council.prompt import DEFAULT_COUNCIL_PROMPT, MAX_PROMPT_CHARS
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _headers(tmp_path):
    return {"X-PM-Token": load_or_create_token(tmp_path)}


def _post(client, tmp_path, **overrides):
    payload = {"project": "myapp", "body": "hello council"}
    payload.update(overrides)
    return client.post("/api/council/board", json=payload, headers=_headers(tmp_path))


# ---------------------------------------------------------------------------
# POST /api/council/board
# ---------------------------------------------------------------------------

def test_post_board_returns_201_with_id(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"].startswith("m-")
    assert data["thread"] == "general"
    assert "ts" in data


def test_post_board_without_token_returns_403(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/council/board", json={"project": "myapp", "body": "hi"})
    assert resp.status_code == 403


def test_post_board_invalid_kind_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, kind="not-a-real-kind")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("kind" in error["msg"].lower() for error in detail)


def test_post_board_invalid_via_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, via="carrier-pigeon")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("via" in error["msg"].lower() for error in detail)


def test_post_board_unknown_field_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, unexpected_field="nope")
    assert resp.status_code == 422


def test_post_board_defaults_via_to_http(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path)
    assert resp.status_code == 201
    get_resp = client.get("/api/council/board", params={"project": "myapp"})
    assert get_resp.json()["messages"][0]["via"] == "http"


def test_post_board_accepts_explicit_mcp_via(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, via="mcp")
    assert resp.status_code == 201
    get_resp = client.get("/api/council/board", params={"project": "myapp"})
    assert get_resp.json()["messages"][0]["via"] == "mcp"


def test_post_board_oversized_body_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, body="x" * 32001)
    assert resp.status_code == 422


def test_post_board_oversized_project_returns_422_not_500(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, project="p" * 400)
    assert resp.status_code == 422


def test_post_board_too_many_refs_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, refs=[f"D-{i:04d}" for i in range(33)])
    assert resp.status_code == 422


def test_post_board_missing_project_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/council/board", json={"body": "hi"}, headers=_headers(tmp_path)
    )
    assert resp.status_code == 422


def test_post_board_missing_body_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/council/board", json={"project": "myapp"}, headers=_headers(tmp_path)
    )
    assert resp.status_code == 422


def test_post_board_empty_project_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, project="")
    assert resp.status_code == 422


def test_post_board_whitespace_project_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, project="   ")
    assert resp.status_code == 422


def test_post_board_oversized_author_and_thread_have_distinct_loc(tmp_path):
    client = _client(tmp_path)
    author_resp = _post(client, tmp_path, author="a" * 65)
    thread_resp = _post(client, tmp_path, thread="t" * 65)

    assert author_resp.status_code == 422
    assert thread_resp.status_code == 422
    author_locs = [error["loc"] for error in author_resp.json()["detail"]]
    thread_locs = [error["loc"] for error in thread_resp.json()["detail"]]
    assert any("author" in loc for loc in author_locs)
    assert any("thread" in loc for loc in thread_locs)
    assert author_locs != thread_locs


def test_post_board_freeform_author_impersonating_another_member_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, author="claude the architect said so")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("author" in error["msg"].lower() for error in detail)


def test_post_board_known_non_member_authors_are_accepted(tmp_path):
    client = _client(tmp_path)
    for author in ("human", "agent"):
        resp = _post(client, tmp_path, author=author)
        assert resp.status_code == 201


def test_post_board_member_id_shaped_author_is_accepted(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, author="codex")
    assert resp.status_code == 201


def test_post_board_oversized_role_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, role="r" * 121)
    assert resp.status_code == 422


def test_post_board_negative_turn_detail_mentions_field(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, turn=-1)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str)
    assert "turn" in detail


def test_post_board_no_orphan_directory_on_validation_error(tmp_path):
    client = _client(tmp_path)
    resp = _post(client, tmp_path, project="never-created", kind="not-a-real-kind")
    assert resp.status_code == 422
    council_dir = tmp_path / "council"
    if council_dir.exists():
        assert not any(council_dir.iterdir())


# ---------------------------------------------------------------------------
# GET /api/council/board
# ---------------------------------------------------------------------------

def test_get_board_empty_project_returns_empty_list(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/council/board", params={"project": "unknown-project"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "unknown-project"
    assert data["messages"] == []
    assert data["count"] == 0


def test_get_board_thread_filter(tmp_path):
    client = _client(tmp_path)
    _post(client, tmp_path, thread="general", body="general note")
    _post(client, tmp_path, thread="c-0001", body="council note")
    resp = client.get(
        "/api/council/board", params={"project": "myapp", "thread": "c-0001"}
    )
    data = resp.json()
    assert data["count"] == 1
    assert data["messages"][0]["thread"] == "c-0001"
    assert data["messages"][0]["body"] == "council note"


def test_get_board_limit_clips_results(tmp_path):
    client = _client(tmp_path)
    for i in range(5):
        _post(client, tmp_path, body=f"message {i}")
    resp = client.get("/api/council/board", params={"project": "myapp", "limit": 2})
    data = resp.json()
    assert data["count"] == 2


def test_get_board_limit_over_max_returns_422(tmp_path):
    client = _client(tmp_path)
    _post(client, tmp_path)
    resp = client.get(
        "/api/council/board", params={"project": "myapp", "limit": 999999}
    )
    assert resp.status_code == 422


def test_get_board_limit_zero_returns_422(tmp_path):
    client = _client(tmp_path)
    _post(client, tmp_path)
    resp = client.get("/api/council/board", params={"project": "myapp", "limit": 0})
    assert resp.status_code == 422


def test_get_board_negative_limit_returns_422(tmp_path):
    client = _client(tmp_path)
    _post(client, tmp_path)
    resp = client.get("/api/council/board", params={"project": "myapp", "limit": -1})
    assert resp.status_code == 422


def test_get_board_since_pages_forward_through_next_messages(tmp_path):
    client = _client(tmp_path)
    ids = []
    for i in range(5):
        resp = _post(client, tmp_path, body=f"message {i}")
        ids.append(resp.json()["id"])
    resp = client.get(
        "/api/council/board", params={"project": "myapp", "since": ids[0], "limit": 2}
    )
    data = resp.json()
    assert [m["id"] for m in data["messages"]] == ids[1:3]


def test_get_board_invalid_since_returns_422(tmp_path):
    client = _client(tmp_path)
    _post(client, tmp_path)
    resp = client.get("/api/council/board", params={"project": "myapp", "since": "zzz"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/council/threads
# ---------------------------------------------------------------------------

def test_get_threads_returns_correct_counts(tmp_path):
    client = _client(tmp_path)
    _post(client, tmp_path, thread="general", body="one")
    _post(client, tmp_path, thread="general", body="two")
    _post(client, tmp_path, thread="c-0001", body="three")
    resp = client.get("/api/council/threads", params={"project": "myapp"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "myapp"
    threads_by_name = {t["thread"]: t for t in data["threads"]}
    assert threads_by_name["general"]["count"] == 2
    assert threads_by_name["c-0001"]["count"] == 1


# ---------------------------------------------------------------------------
# End-to-end: post then read
# ---------------------------------------------------------------------------

def test_post_then_get_board_sees_message(tmp_path):
    client = _client(tmp_path)
    post_resp = _post(client, tmp_path, body="the decision is made")
    message_id = post_resp.json()["id"]
    get_resp = client.get("/api/council/board", params={"project": "myapp"})
    bodies = [m["body"] for m in get_resp.json()["messages"]]
    ids = [m["id"] for m in get_resp.json()["messages"]]
    assert "the decision is made" in bodies
    assert message_id in ids


# ---------------------------------------------------------------------------
# GET/POST /api/council/prompt
# ---------------------------------------------------------------------------

def test_get_prompt_default_state(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/council/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] is None
    assert data["is_default"] is True
    assert data["default_text"] == DEFAULT_COUNCIL_PROMPT


def test_post_prompt_saves_and_get_reflects_it(tmp_path):
    client = _client(tmp_path)
    post_resp = client.post(
        "/api/council/prompt", json={"text": "custom global prompt"}, headers=_headers(tmp_path)
    )
    assert post_resp.status_code in (200, 201)

    get_resp = client.get("/api/council/prompt")
    data = get_resp.json()
    assert data["text"] == "custom global prompt"
    assert data["is_default"] is False


def test_post_prompt_without_token_returns_403(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/council/prompt", json={"text": "custom"})
    assert resp.status_code == 403


def test_post_prompt_empty_text_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/council/prompt", json={"text": "   "}, headers=_headers(tmp_path))
    assert resp.status_code == 422


def test_post_prompt_oversized_text_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/council/prompt",
        json={"text": "x" * (MAX_PROMPT_CHARS + 1)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_post_prompt_reset_removes_override(tmp_path):
    client = _client(tmp_path)
    client.post("/api/council/prompt", json={"text": "custom"}, headers=_headers(tmp_path))
    reset_resp = client.post("/api/council/prompt/reset", headers=_headers(tmp_path))
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "reset"

    get_resp = client.get("/api/council/prompt")
    assert get_resp.json()["text"] is None
    assert get_resp.json()["is_default"] is True


def test_post_prompt_reset_without_token_returns_403(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/council/prompt/reset")
    assert resp.status_code == 403


def test_get_prompt_broken_utf8_file_returns_422_not_500(tmp_path):
    client = _client(tmp_path)
    council_dir = tmp_path / "council"
    council_dir.mkdir(parents=True, exist_ok=True)
    (council_dir / "prompt.md").write_bytes(b"\xff\xfe not utf-8")

    resp = client.get("/api/council/prompt")
    assert resp.status_code == 422


def test_get_prompt_oversized_file_returns_422_not_500(tmp_path):
    client = _client(tmp_path)
    council_dir = tmp_path / "council"
    council_dir.mkdir(parents=True, exist_ok=True)
    (council_dir / "prompt.md").write_text("x" * (MAX_PROMPT_CHARS + 1), encoding="utf-8")

    resp = client.get("/api/council/prompt")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# MAJOR 4 — optimistic concurrency for POST /api/council/prompt: two tabs/
# agents editing at once must not silently clobber one another.
# ---------------------------------------------------------------------------


def test_get_prompt_version_is_zero_when_no_file_exists(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/council/prompt")
    assert resp.json()["version"] == "0"


def test_post_prompt_without_version_overwrites_unconditionally(tmp_path):
    client = _client(tmp_path)
    client.post("/api/council/prompt", json={"text": "first"}, headers=_headers(tmp_path))
    resp = client.post("/api/council/prompt", json={"text": "second"}, headers=_headers(tmp_path))
    assert resp.status_code in (200, 201)
    assert client.get("/api/council/prompt").json()["text"] == "second"


def test_post_prompt_with_matching_version_succeeds(tmp_path):
    client = _client(tmp_path)
    client.post("/api/council/prompt", json={"text": "first"}, headers=_headers(tmp_path))
    version = client.get("/api/council/prompt").json()["version"]

    resp = client.post(
        "/api/council/prompt", json={"text": "second", "version": version}, headers=_headers(tmp_path)
    )

    assert resp.status_code in (200, 201)
    assert client.get("/api/council/prompt").json()["text"] == "second"


def test_post_prompt_with_stale_version_returns_409_and_does_not_overwrite(tmp_path):
    client = _client(tmp_path)
    client.post("/api/council/prompt", json={"text": "tab A base"}, headers=_headers(tmp_path))
    stale_version = client.get("/api/council/prompt").json()["version"]

    # A second writer (another tab/agent) saves in between.
    client.post("/api/council/prompt", json={"text": "tab B wins the race"}, headers=_headers(tmp_path))

    resp = client.post(
        "/api/council/prompt", json={"text": "tab A stale edit", "version": stale_version}, headers=_headers(tmp_path)
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]
    assert client.get("/api/council/prompt").json()["text"] == "tab B wins the race"


def test_post_prompt_with_version_against_missing_file_returns_409(tmp_path):
    client = _client(tmp_path)

    resp = client.post(
        "/api/council/prompt", json={"text": "first write", "version": "123"}, headers=_headers(tmp_path)
    )

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/council/config
# ---------------------------------------------------------------------------

@pytest.fixture
def home_project_dir():
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        (Path(tmp) / ".git").mkdir()
        yield Path(tmp)


def test_get_config_missing_file_returns_default(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "myapp"
    assert data["source"] == "default"
    assert data["config"]["version"] == 1
    assert isinstance(data["prompt_layers"], list)
    assert data["prompt_layers"][0]["layer"] == "default"


def test_get_config_reads_project_file(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_text(
        """
version: 1
spokesperson: claude
rounds: 3
members:
  - {id: claude, backend: claude, role: "Architect"}
""",
        encoding="utf-8",
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "file"
    assert data["config"]["rounds"] == 3


def test_get_config_broken_yaml_returns_422_not_500(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_text("version: [1, 2\nmembers: broken", encoding="utf-8")
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_invalid_cwd_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": "/etc/does-not-exist-council"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_relative_cwd_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": "relative/path"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_missing_cwd_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config", params={"project": "myapp"}, headers=_headers(tmp_path)
    )
    assert resp.status_code == 422


def test_get_config_without_token_returns_403(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config", params={"project": "myapp", "cwd": str(home_project_dir)}
    )
    assert resp.status_code == 403


def test_get_config_invalid_cwd_error_omits_absolute_path(tmp_path):
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": "/etc/does-not-exist-council"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422
    assert "/etc/does-not-exist-council" not in resp.json()["detail"]


def test_get_config_cwd_with_only_pm_council_yaml_marker_is_accepted(tmp_path):
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        (Path(tmp) / CONFIG_FILENAME).write_text(
            "version: 1\nmembers:\n  - {id: claude, backend: claude}\n", encoding="utf-8"
        )
        client = _client(tmp_path)
        resp = client.get(
            "/api/council/config",
            params={"project": "myapp", "cwd": tmp},
            headers=_headers(tmp_path),
        )
        assert resp.status_code == 200


def test_get_config_cwd_without_project_markers_returns_422(tmp_path):
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        client = _client(tmp_path)
        resp = client.get(
            "/api/council/config",
            params={"project": "myapp", "cwd": tmp},
            headers=_headers(tmp_path),
        )
        assert resp.status_code == 422
        assert "project root" in resp.json()["detail"]


def test_get_config_outside_allowed_roots_uses_pm_cwd_roots(tmp_path, monkeypatch):
    outside_root = tmp_path / "outside-root"
    project_dir = outside_root / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / ".git").mkdir()
    client = _client(tmp_path)

    resp_before = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp_before.status_code == 422

    monkeypatch.setenv("PM_CWD_ROOTS", str(outside_root))
    resp_after = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp_after.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/council/config: malformed .pm-council.yaml must never be a 500
# ---------------------------------------------------------------------------

def test_get_config_non_string_yaml_key_returns_422_not_500(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_text(
        "1: stray-value\nversion: 1\nmembers:\n  - {id: claude, backend: claude}\n",
        encoding="utf-8",
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_broken_utf8_returns_422_not_500(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_bytes(b"version: 1\nmembers: []\n\xff\xfe")
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_deeply_nested_yaml_returns_422_not_500(tmp_path, home_project_dir):
    nesting = 60000
    (home_project_dir / CONFIG_FILENAME).write_text(
        "a: " + "[" * nesting + "]" * nesting, encoding="utf-8"
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_oversized_file_returns_422_not_500(tmp_path, home_project_dir):
    padding_line = "# padding\n"
    (home_project_dir / CONFIG_FILENAME).write_text(
        "version: 1\nmembers:\n  - {id: claude, backend: claude}\n"
        + padding_line * (MAX_CONFIG_BYTES // len(padding_line) + 1),
        encoding="utf-8",
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_too_many_members_returns_422_not_500(tmp_path, home_project_dir):
    members_block = "\n".join(f"  - {{id: m{i}, backend: claude}}" for i in range(MAX_MEMBERS + 1))
    (home_project_dir / CONFIG_FILENAME).write_text(
        f"version: 1\nmembers:\n{members_block}\n", encoding="utf-8"
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_turn_call_cap_exceeded_returns_422_not_500(tmp_path, home_project_dir):
    members_block = "\n".join(f"  - {{id: m{i}, backend: claude}}" for i in range(MAX_MEMBERS))
    (home_project_dir / CONFIG_FILENAME).write_text(
        f"version: 1\nrounds: {MAX_ROUNDS}\nmembers:\n{members_block}\n", encoding="utf-8"
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_bad_member_id_returns_422_not_500(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_text(
        "version: 1\nmembers:\n  - {id: '../../../../etc/passwd', backend: claude}\n",
        encoding="utf-8",
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_get_config_flag_injection_model_returns_422_not_500(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_text(
        "version: 1\nmembers:\n  - {id: claude, backend: claude, model: --dangerously-skip-permissions}\n",
        encoding="utf-8",
    )
    client = _client(tmp_path)
    resp = client.get(
        "/api/council/config",
        params={"project": "myapp", "cwd": str(home_project_dir)},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422
