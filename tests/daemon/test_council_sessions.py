"""Tests for the AI Council session HTTP endpoints."""

import ast
import json
import signal
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import persistent_memory.council.api as council_api
from persistent_memory.council.config import CONFIG_FILENAME
from persistent_memory.council.session import list_sessions, read_session, session_path, update_session
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _headers(tmp_path):
    return {"X-PM-Token": load_or_create_token(tmp_path)}


class _FakeProc:
    def __init__(self, returncode=None, respond_to_sigterm=True):
        self._returncode = returncode
        self.killed = False
        self.terminated = False
        self.pid = 4242424
        self._respond_to_sigterm = respond_to_sigterm

    def poll(self):
        return self._returncode

    def send_signal(self, sig):
        self.terminated = True
        if self._respond_to_sigterm:
            self._returncode = 0

    def kill(self):
        self.killed = True
        self._returncode = -9


@pytest.fixture(autouse=True)
def _reset_council(monkeypatch):
    def fake_popen(argv, **kwargs):
        return _FakeProc(returncode=None)

    monkeypatch.setattr(council_api.subprocess, "Popen", fake_popen)
    council_api.reset_council_state()
    yield
    council_api.reset_council_state()


@pytest.fixture
def home_project_dir():
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        (Path(tmp) / ".git").mkdir()
        yield Path(tmp)


def _open_session(client, tmp_path, home_project_dir, **overrides):
    payload = {"project": "myapp", "cwd": str(home_project_dir), "topic": "should we ship X?"}
    payload.update(overrides)
    return client.post("/api/council/sessions", json=payload, headers=_headers(tmp_path))


# ---------------------------------------------------------------------------
# Layer boundary: api.py must not reach into runner.py's private names
# ---------------------------------------------------------------------------

def test_api_module_imports_no_private_runner_names():
    source = Path(council_api.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    private_imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "persistent_memory.council.runner"
        for alias in node.names
        if alias.name.startswith("_")
    ]
    assert private_imports == []


# ---------------------------------------------------------------------------
# POST /api/council/sessions
# ---------------------------------------------------------------------------

def test_post_session_returns_202_and_creates_session_file(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir)
    assert resp.status_code == 202
    data = resp.json()
    assert data["id"].startswith("c-")
    assert data["thread"] == data["id"]
    assert set(data["members"]) == {"claude", "codex", "grok"}
    assert data["rounds"] == 2
    assert data["estimated_calls"] == 7
    assert "log_dir" in data

    session = read_session(DaemonConfig(records_dir=tmp_path).council_dir, "myapp", data["id"])
    assert session.status == "pending"
    assert session.thread == session.id


def test_post_session_without_token_returns_403(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = client.post(
        "/api/council/sessions",
        json={"project": "myapp", "cwd": str(home_project_dir), "topic": "x"},
    )
    assert resp.status_code == 403


def test_post_session_invalid_cwd_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/council/sessions",
        json={"project": "myapp", "cwd": "/etc/does-not-exist-council", "topic": "x"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422


def test_post_session_unknown_member_returns_422(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, members=["not-a-member"])
    assert resp.status_code == 422
    assert "not-a-member" in resp.json()["detail"]


def test_post_session_disabled_member_requested_explicitly_returns_422(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_text(
        "version: 1\nrounds: 1\nmembers:\n"
        "  - {id: claude, backend: claude}\n"
        "  - {id: codex, backend: codex, enabled: false}\n",
        encoding="utf-8",
    )
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, members=["codex"])
    assert resp.status_code == 422
    assert "codex" in resp.json()["detail"]


def test_post_session_member_subset_is_accepted(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, members=["claude"])
    assert resp.status_code == 202
    assert resp.json()["members"] == ["claude"]
    assert resp.json()["estimated_calls"] == 3  # 1 member x 2 rounds + 1 synthesis


def test_post_session_rounds_exceeding_call_cap_returns_422(tmp_path, home_project_dir):
    (home_project_dir / CONFIG_FILENAME).write_text(
        "version: 1\nrounds: 2\nmembers:\n"
        + "\n".join(f"  - {{id: m{i}, backend: claude}}" for i in range(5))
        + "\n",
        encoding="utf-8",
    )
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, rounds=5)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "26" in detail  # 5 members x 5 rounds + 1 synthesis


def test_post_session_second_active_session_in_same_project_returns_409(tmp_path, home_project_dir):
    client = _client(tmp_path)
    first = _open_session(client, tmp_path, home_project_dir)
    assert first.status_code == 202
    first_id = first.json()["id"]

    second = _open_session(client, tmp_path, home_project_dir, topic="a different question")
    assert second.status_code == 409
    assert first_id in second.json()["detail"]


def test_post_session_different_project_is_not_blocked(tmp_path, home_project_dir):
    client = _client(tmp_path)
    first = _open_session(client, tmp_path, home_project_dir, project="app-one")
    assert first.status_code == 202

    second = _open_session(client, tmp_path, home_project_dir, project="app-two")
    assert second.status_code == 202


def test_post_session_dry_run_does_not_create_session_and_returns_prompts(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, dry_run=True)
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert set(data["prompts"].keys()) == {"claude", "codex", "grok"}
    for prompt_text in data["prompts"].values():
        assert "should we ship X?" in prompt_text

    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    assert list_sessions(council_dir, "myapp") == []


def test_post_session_dry_run_missing_member_still_validated(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, dry_run=True, members=["ghost"])
    assert resp.status_code == 422


def test_post_session_empty_members_list_returns_422(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, members=[])
    assert resp.status_code == 422


def test_post_session_empty_topic_returns_422(tmp_path, home_project_dir):
    client = _client(tmp_path)
    resp = _open_session(client, tmp_path, home_project_dir, topic="   ")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/council/sessions, GET /api/council/sessions/{id}
# ---------------------------------------------------------------------------

def test_get_sessions_list_no_token_required(tmp_path, home_project_dir):
    client = _client(tmp_path)
    _open_session(client, tmp_path, home_project_dir)
    resp = client.get("/api/council/sessions", params={"project": "myapp"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "myapp"
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["status"] == "pending"


def test_get_sessions_list_newest_first(tmp_path, home_project_dir):
    client = _client(tmp_path)
    _open_session(client, tmp_path, home_project_dir, project="multi")
    client.post(
        f"/api/council/sessions/{_first_session_id(client, tmp_path, 'multi')}/cancel",
        params={"project": "multi"},
        headers=_headers(tmp_path),
    )
    second = _open_session(client, tmp_path, home_project_dir, project="multi")
    resp = client.get("/api/council/sessions", params={"project": "multi"})
    ids = [s["id"] for s in resp.json()["sessions"]]
    assert ids[0] == second.json()["id"]


def _first_session_id(client, tmp_path, project):
    resp = client.get("/api/council/sessions", params={"project": project})
    return resp.json()["sessions"][0]["id"]


def test_get_session_detail_returns_full_state_including_turns(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    resp = client.get(f"/api/council/sessions/{session_id}", params={"project": "myapp"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == session_id
    assert "turns" in data
    assert data["turns"] == []


def test_get_session_detail_does_not_leak_project_root(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    resp = client.get(f"/api/council/sessions/{session_id}", params={"project": "myapp"})
    assert resp.status_code == 200
    assert "project_root" not in resp.json()


def test_get_session_corrupt_file_error_does_not_leak_absolute_path(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    session_path = council_dir / "myapp" / "sessions" / f"{session_id}.json"
    session_path.write_text("{not valid json", encoding="utf-8")

    resp = client.get(f"/api/council/sessions/{session_id}", params={"project": "myapp"})
    assert resp.status_code == 404
    assert str(tmp_path) not in resp.json()["detail"]


def test_get_session_detail_no_token_required(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    resp = client.get(f"/api/council/sessions/{session_id}", params={"project": "myapp"})
    assert resp.status_code == 200


def test_get_session_not_found_returns_404(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/council/sessions/c-9999", params={"project": "myapp"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Zombie-launcher pruning (_prune_finished_councils)
# ---------------------------------------------------------------------------

def test_get_sessions_list_prunes_dead_launcher_and_marks_session_failed(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    proc = council_api._council_procs[session_id][1]
    proc._returncode = 1  # runner crashed without ever updating session.json

    resp = client.get("/api/council/sessions", params={"project": "myapp"})
    assert resp.status_code == 200

    session = read_session(DaemonConfig(records_dir=tmp_path).council_dir, "myapp", session_id)
    assert session.status == "failed"
    assert session.error == "runner exited unexpectedly"
    assert session_id not in council_api._council_procs


def test_post_session_prunes_dead_launcher_freeing_active_slot(tmp_path, home_project_dir):
    client = _client(tmp_path)
    first_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    proc = council_api._council_procs[first_id][1]
    proc._returncode = 1

    second = _open_session(client, tmp_path, home_project_dir, topic="a different question")
    assert second.status_code == 202

    first_session = read_session(DaemonConfig(records_dir=tmp_path).council_dir, "myapp", first_id)
    assert first_session.status == "failed"


def test_prune_does_not_overwrite_already_finished_session(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    proc = council_api._council_procs[session_id][1]
    proc._returncode = 0

    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    session = read_session(council_dir, "myapp", session_id)
    session = session.model_copy(update={"status": "converged", "finished_at": "2026-07-24T00:00:00Z"})
    update_session(council_dir, session)

    client.get("/api/council/sessions", params={"project": "myapp"})

    reloaded = read_session(council_dir, "myapp", session_id)
    assert reloaded.status == "converged"
    assert reloaded.error is None


# ---------------------------------------------------------------------------
# POST /api/council/sessions/{id}/cancel
# ---------------------------------------------------------------------------

def test_cancel_session_sends_sigterm_for_graceful_shutdown_and_marks_cancelled(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    proc = council_api._council_procs[session_id][1]

    resp = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert proc.terminated is True
    assert proc.killed is False

    session = read_session(DaemonConfig(records_dir=tmp_path).council_dir, "myapp", session_id)
    assert session.status == "cancelled"
    assert session.finished_at is not None


def test_cancel_session_force_kills_launcher_when_it_ignores_sigterm(tmp_path, home_project_dir, monkeypatch):
    monkeypatch.setattr(council_api, "CANCEL_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(council_api, "CANCEL_POLL_INTERVAL_SECONDS", 0.01)

    def fake_popen(argv, **kwargs):
        return _FakeProc(returncode=None, respond_to_sigterm=False)

    monkeypatch.setattr(council_api.subprocess, "Popen", fake_popen)

    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    proc = council_api._council_procs[session_id][1]

    resp = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    assert proc.terminated is True
    assert proc.killed is True

    session = read_session(DaemonConfig(records_dir=tmp_path).council_dir, "myapp", session_id)
    assert session.status == "cancelled"


def test_cancel_session_without_token_returns_403(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    resp = client.post(f"/api/council/sessions/{session_id}/cancel", params={"project": "myapp"})
    assert resp.status_code == 403


def test_cancel_already_finished_session_returns_409(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    first = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert second.status_code == 409


def test_cancel_session_not_found_returns_404(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/council/sessions/c-9999/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 404


def test_cancel_uses_pid_channel_fallback_when_daemon_procs_are_lost(tmp_path, home_project_dir, monkeypatch):
    # Simulates a daemon restart: session.json still has the runner's own
    # pid/pgid (written by main()), but _council_procs (in-process only) is
    # empty, so the launcher Popen handle is unknown to this process.
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]

    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    session = read_session(council_dir, "myapp", session_id)
    session = session.model_copy(update={"runner_pid": 424242, "runner_pgid": 424242})
    update_session(council_dir, session)
    council_api.reset_council_state()

    ps_calls = []

    def fake_run(argv, **kwargs):
        ps_calls.append(argv)

        class _Result:
            stdout = "/usr/bin/python -m persistent_memory.council.runner --records-dir x"

        return _Result()

    monkeypatch.setattr(council_api.subprocess, "run", fake_run)

    killpg_calls = []

    def fake_killpg(pgid, sig):
        killpg_calls.append((pgid, sig))
        if sig == signal.SIGTERM:
            raise ProcessLookupError()

    monkeypatch.setattr(council_api.os, "killpg", fake_killpg)

    resp = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert ps_calls
    assert (424242, signal.SIGTERM) in killpg_calls

    updated = read_session(council_dir, "myapp", session_id)
    assert updated.status == "cancelled"
    assert updated.runner_pid is None
    assert updated.runner_pgid is None


def test_cancel_pid_channel_refuses_to_signal_a_stale_reused_pid(tmp_path, home_project_dir, monkeypatch):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]

    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    session = read_session(council_dir, "myapp", session_id)
    session = session.model_copy(update={"runner_pid": 999999, "runner_pgid": 999999})
    update_session(council_dir, session)
    council_api.reset_council_state()

    def fake_run(argv, **kwargs):
        class _Result:
            stdout = "/usr/bin/some-unrelated-process"

        return _Result()

    monkeypatch.setattr(council_api.subprocess, "run", fake_run)

    killpg_calls = []
    monkeypatch.setattr(council_api.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))

    resp = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    assert killpg_calls == []

    updated = read_session(council_dir, "myapp", session_id)
    assert updated.status == "cancelled"


def test_cancel_pid_channel_force_kills_when_runner_ignores_sigterm(tmp_path, home_project_dir, monkeypatch):
    monkeypatch.setattr(council_api, "CANCEL_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(council_api, "CANCEL_POLL_INTERVAL_SECONDS", 0.01)

    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    session = read_session(council_dir, "myapp", session_id)
    session = session.model_copy(update={"runner_pid": 555, "runner_pgid": 555})
    update_session(council_dir, session)
    council_api.reset_council_state()

    def fake_run(argv, **kwargs):
        class _Result:
            stdout = "python -m persistent_memory.council.runner"

        return _Result()

    monkeypatch.setattr(council_api.subprocess, "run", fake_run)

    killpg_calls = []
    monkeypatch.setattr(council_api.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))

    resp = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    assert (555, signal.SIGTERM) in killpg_calls
    assert (555, signal.SIGKILL) in killpg_calls


def test_cancel_prefers_council_procs_over_pid_channel_when_both_available(tmp_path, home_project_dir, monkeypatch):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    session = read_session(council_dir, "myapp", session_id)
    session = session.model_copy(update={"runner_pid": 111, "runner_pgid": 111})
    update_session(council_dir, session)

    ps_calls = []
    monkeypatch.setattr(
        council_api.subprocess, "run", lambda argv, **kwargs: ps_calls.append(argv) or None
    )

    proc = council_api._council_procs[session_id][1]

    resp = client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    assert proc.terminated is True
    assert ps_calls == []


def test_cancel_allows_reopening_session_for_project(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    resp = _open_session(client, tmp_path, home_project_dir, topic="reopened topic")
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /api/council/sessions/all
# ---------------------------------------------------------------------------

def test_get_all_sessions_empty_returns_empty_list(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/council/sessions/all")
    assert resp.status_code == 200
    assert resp.json() == {"sessions": []}


def test_get_all_sessions_no_token_required(tmp_path, home_project_dir):
    client = _client(tmp_path)
    _open_session(client, tmp_path, home_project_dir)
    resp = client.get("/api/council/sessions/all")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 1


def test_get_all_sessions_combines_multiple_projects(tmp_path, home_project_dir):
    client = _client(tmp_path)
    _open_session(client, tmp_path, home_project_dir, project="proj-a")
    _open_session(client, tmp_path, home_project_dir, project="proj-b")

    resp = client.get("/api/council/sessions/all")
    assert resp.status_code == 200
    projects = {session["project"] for session in resp.json()["sessions"]}
    assert projects == {"proj-a", "proj-b"}


def test_get_all_sessions_summary_shape(tmp_path, home_project_dir):
    client = _client(tmp_path)
    _open_session(client, tmp_path, home_project_dir)

    resp = client.get("/api/council/sessions/all")
    entry = resp.json()["sessions"][0]
    assert set(entry.keys()) == {
        "id", "project", "topic", "status", "rounds", "members",
        "created_at", "finished_at", "record_id", "thread",
    }


def test_get_all_sessions_truncates_long_topic(tmp_path, home_project_dir):
    client = _client(tmp_path)
    long_topic = "x" * 500
    _open_session(client, tmp_path, home_project_dir, topic=long_topic)

    resp = client.get("/api/council/sessions/all")
    topic = resp.json()["sessions"][0]["topic"]
    assert len(topic) == 141
    assert topic.endswith("…")
    assert topic[:-1] == "x" * 140


def test_get_all_sessions_orders_active_sessions_before_finished_ones(tmp_path, home_project_dir):
    client = _client(tmp_path)
    council_dir = DaemonConfig(records_dir=tmp_path).council_dir

    finished_id = _open_session(client, tmp_path, home_project_dir, project="p1").json()["id"]
    finished = read_session(council_dir, "p1", finished_id)
    finished = finished.model_copy(
        update={"status": "converged", "finished_at": "2026-06-01T00:00:00Z", "created_at": "2026-06-01T00:00:00Z"}
    )
    update_session(council_dir, finished)

    active_id = _open_session(client, tmp_path, home_project_dir, project="p1", topic="second").json()["id"]
    active = read_session(council_dir, "p1", active_id)
    active = active.model_copy(update={"created_at": "2020-01-01T00:00:00Z"})
    update_session(council_dir, active)

    resp = client.get("/api/council/sessions/all")
    ids = [session["id"] for session in resp.json()["sessions"]]
    assert ids == [active_id, finished_id]


def test_get_all_sessions_orders_by_created_at_desc_within_same_status(tmp_path, home_project_dir):
    client = _client(tmp_path)
    council_dir = DaemonConfig(records_dir=tmp_path).council_dir

    first_id = _open_session(client, tmp_path, home_project_dir, project="p1").json()["id"]
    client.post(
        f"/api/council/sessions/{first_id}/cancel", params={"project": "p1"}, headers=_headers(tmp_path)
    )
    first = read_session(council_dir, "p1", first_id).model_copy(update={"created_at": "2026-01-01T00:00:00Z"})
    update_session(council_dir, first)

    second_id = _open_session(
        client, tmp_path, home_project_dir, project="p1", topic="second"
    ).json()["id"]
    client.post(
        f"/api/council/sessions/{second_id}/cancel", params={"project": "p1"}, headers=_headers(tmp_path)
    )
    second = read_session(council_dir, "p1", second_id).model_copy(update={"created_at": "2026-02-01T00:00:00Z"})
    update_session(council_dir, second)

    resp = client.get("/api/council/sessions/all")
    ids = [session["id"] for session in resp.json()["sessions"]]
    assert ids.index(second_id) < ids.index(first_id)


def test_get_all_sessions_active_only_filters_out_finished(tmp_path, home_project_dir):
    client = _client(tmp_path)
    finished_id = _open_session(client, tmp_path, home_project_dir, project="p1").json()["id"]
    client.post(
        f"/api/council/sessions/{finished_id}/cancel", params={"project": "p1"}, headers=_headers(tmp_path)
    )
    active_id = _open_session(client, tmp_path, home_project_dir, project="p2").json()["id"]

    resp = client.get("/api/council/sessions/all", params={"active_only": "true"})
    ids = [session["id"] for session in resp.json()["sessions"]]
    assert ids == [active_id]


def test_get_all_sessions_limit_caps_result_count(tmp_path, home_project_dir):
    client = _client(tmp_path)
    for i in range(3):
        _open_session(client, tmp_path, home_project_dir, project=f"p{i}")

    resp = client.get("/api/council/sessions/all", params={"limit": 2})
    assert len(resp.json()["sessions"]) == 2


def test_get_all_sessions_limit_above_max_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/council/sessions/all", params={"limit": 100000})
    assert resp.status_code == 422


def test_get_all_sessions_skips_corrupt_session_file(tmp_path, home_project_dir):
    client = _client(tmp_path)
    good_id = _open_session(client, tmp_path, home_project_dir, project="good").json()["id"]

    council_dir = DaemonConfig(records_dir=tmp_path).council_dir
    corrupt_sessions_dir = council_dir / "corrupt-project" / "sessions"
    corrupt_sessions_dir.mkdir(parents=True)
    (corrupt_sessions_dir / "c-0001.json").write_text("{not valid json", encoding="utf-8")

    resp = client.get("/api/council/sessions/all")
    assert resp.status_code == 200
    ids = [session["id"] for session in resp.json()["sessions"]]
    assert ids == [good_id]


# ---------------------------------------------------------------------------
# GET /api/council/stream (SSE)
# ---------------------------------------------------------------------------

def _collect_sse_until(line_iterator, predicate, max_lines=1000):
    events = []
    current_event = None
    for i, line in enumerate(line_iterator):
        if i >= max_lines:
            break
        if line.startswith("event: "):
            current_event = line[len("event: "):]
            continue
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
            events.append((current_event, payload))
            if predicate(current_event, payload):
                break
    return events


@pytest.fixture(autouse=True)
def _fast_stream_timings(monkeypatch):
    monkeypatch.setattr(council_api, "STREAM_POLL_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(council_api, "STREAM_HEARTBEAT_SECONDS", 30)
    monkeypatch.setattr(council_api, "STREAM_MAX_SECONDS", 0.1)
    yield


def test_stream_no_token_required(tmp_path):
    client = _client(tmp_path)
    with client.stream("GET", "/api/council/stream", params={"project": "myapp"}) as resp:
        assert resp.status_code == 200


def test_stream_response_is_event_stream_content_type(tmp_path):
    client = _client(tmp_path)
    with client.stream("GET", "/api/council/stream", params={"project": "myapp"}) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")


def test_stream_emits_message_event_for_preexisting_board_message(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/api/council/board",
        json={"project": "myapp", "body": "hello world"},
        headers=_headers(tmp_path),
    )
    with client.stream("GET", "/api/council/stream", params={"project": "myapp"}) as resp:
        events = _collect_sse_until(
            resp.iter_lines(), lambda event, data: event == "message" and data.get("body") == "hello world"
        )
    assert events, "expected a message event"
    assert events[-1][0] == "message"
    assert events[-1][1]["body"] == "hello world"
    assert events[-1][1]["project"] == "myapp"


def test_stream_emits_session_event_for_existing_session(tmp_path, home_project_dir):
    client = _client(tmp_path)
    session_id = _open_session(client, tmp_path, home_project_dir).json()["id"]
    client.post(
        f"/api/council/sessions/{session_id}/cancel",
        params={"project": "myapp"},
        headers=_headers(tmp_path),
    )
    with client.stream(
        "GET", "/api/council/stream", params={"project": "myapp", "session": session_id}
    ) as resp:
        events = _collect_sse_until(
            resp.iter_lines(), lambda event, data: event == "session" and data.get("status") == "cancelled"
        )
    assert events, "expected a session event with status=cancelled"
    assert events[-1][0] == "session"
    assert events[-1][1]["status"] == "cancelled"
    assert events[-1][1]["id"] == session_id
    assert "project_root" not in events[-1][1]


def test_stream_without_session_param_emits_only_board_messages(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/api/council/board",
        json={"project": "myapp", "body": "no session here"},
        headers=_headers(tmp_path),
    )
    with client.stream("GET", "/api/council/stream", params={"project": "myapp"}) as resp:
        events = _collect_sse_until(
            resp.iter_lines(), lambda event, data: event == "message" and data.get("body") == "no session here"
        )
    assert events[-1][1]["body"] == "no session here"
    assert all(event != "session" for event, _ in events)


def test_stream_emits_ping_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(council_api, "STREAM_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(council_api, "STREAM_MAX_SECONDS", 0.3)
    client = _client(tmp_path)
    with client.stream("GET", "/api/council/stream", params={"project": "myapp"}) as resp:
        events = _collect_sse_until(resp.iter_lines(), lambda event, data: event == "ping")
    assert events, "expected a ping heartbeat event"
    assert events[-1][0] == "ping"
    assert "ts" in events[-1][1]


def test_stream_closes_after_max_stream_seconds(tmp_path, monkeypatch):
    monkeypatch.setattr(council_api, "STREAM_MAX_SECONDS", 0.05)
    monkeypatch.setattr(council_api, "STREAM_HEARTBEAT_SECONDS", 30)
    client = _client(tmp_path)
    with client.stream("GET", "/api/council/stream", params={"project": "myapp"}) as resp:
        lines = list(resp.iter_lines())
    assert lines == []
