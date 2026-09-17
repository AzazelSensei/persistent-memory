"""Tests for the AI Council session model and file store."""

import json
import threading

import pytest
from pydantic import ValidationError

from persistent_memory.council.session import (
    ACTIVE_SESSION_STATUSES,
    MAX_TOPIC_CHARS,
    CouncilActiveSessionError,
    CouncilSession,
    CouncilSessionError,
    CouncilTurnState,
    create_session,
    list_sessions,
    next_session_id,
    read_session,
    sessions_dir,
    update_session,
    update_session_with,
)


def _council_dir(tmp_path):
    return tmp_path / "council"


def _fields(**overrides):
    fields = {
        "project": "alpha",
        "project_root": "/repo/alpha",
        "topic": "should we adopt X",
        "thread": "c-0001",
        "status": "pending",
        "rounds": 2,
        "members": ["claude", "codex"],
        "spokesperson": "claude",
    }
    fields.update(overrides)
    return fields


# ---------------------------------------------------------------------------
# CouncilTurnState / CouncilSession model validation
# ---------------------------------------------------------------------------


def test_council_turn_state_valid_construction():
    turn = CouncilTurnState(round=1, member_id="claude", status="pending")

    assert turn.round == 1
    assert turn.status == "pending"
    assert turn.started_at is None


def test_council_turn_state_rejects_invalid_status():
    with pytest.raises(ValidationError):
        CouncilTurnState(round=1, member_id="claude", status="not-a-real-status")


def test_council_turn_state_rejects_round_below_one():
    with pytest.raises(ValidationError):
        CouncilTurnState(round=0, member_id="claude", status="pending")


def test_council_turn_state_rejects_invalid_member_id():
    with pytest.raises(ValidationError):
        CouncilTurnState(round=1, member_id="../etc/passwd", status="pending")


def test_council_session_valid_construction():
    session = CouncilSession(
        id="c-0001",
        created_at="2026-07-24T00:00:00Z",
        **_fields(),
    )

    assert session.id == "c-0001"
    assert session.turns == []
    assert session.record_id is None


def test_council_session_rejects_invalid_id_format():
    with pytest.raises(ValidationError):
        CouncilSession(id="not-c-format", created_at="2026-07-24T00:00:00Z", **_fields())


def test_council_session_rejects_empty_topic():
    with pytest.raises(ValidationError):
        CouncilSession(id="c-0001", created_at="2026-07-24T00:00:00Z", **_fields(topic=""))


def test_council_session_rejects_whitespace_only_topic():
    with pytest.raises(ValidationError):
        CouncilSession(id="c-0001", created_at="2026-07-24T00:00:00Z", **_fields(topic="   "))


def test_council_session_rejects_oversized_topic():
    with pytest.raises(ValidationError):
        CouncilSession(
            id="c-0001",
            created_at="2026-07-24T00:00:00Z",
            **_fields(topic="x" * (MAX_TOPIC_CHARS + 1)),
        )


def test_council_session_rejects_invalid_status():
    with pytest.raises(ValidationError):
        CouncilSession(id="c-0001", created_at="2026-07-24T00:00:00Z", **_fields(status="not-a-status"))


def test_council_session_rejects_invalid_member_id_in_members():
    with pytest.raises(ValidationError):
        CouncilSession(
            id="c-0001",
            created_at="2026-07-24T00:00:00Z",
            **_fields(members=["claude", "; rm -rf ~"]),
        )


def test_council_session_rejects_invalid_spokesperson_format():
    with pytest.raises(ValidationError):
        CouncilSession(
            id="c-0001",
            created_at="2026-07-24T00:00:00Z",
            **_fields(spokesperson="--dangerous"),
        )


def test_council_session_defaults_runner_pid_and_pgid_to_none():
    session = CouncilSession(id="c-0001", created_at="2026-07-24T00:00:00Z", **_fields())

    assert session.runner_pid is None
    assert session.runner_pgid is None


def test_council_session_accepts_runner_pid_and_pgid():
    session = CouncilSession(
        id="c-0001", created_at="2026-07-24T00:00:00Z", runner_pid=4242, runner_pgid=4242, **_fields()
    )

    assert session.runner_pid == 4242
    assert session.runner_pgid == 4242


def test_council_turn_state_accepts_cancelled_status():
    turn = CouncilTurnState(round=1, member_id="claude", status="cancelled")

    assert turn.status == "cancelled"


def test_council_session_accepts_turns():
    session = CouncilSession(
        id="c-0001",
        created_at="2026-07-24T00:00:00Z",
        turns=[CouncilTurnState(round=1, member_id="claude", status="done")],
        **_fields(),
    )

    assert len(session.turns) == 1
    assert session.turns[0].status == "done"


# ---------------------------------------------------------------------------
# next_session_id
# ---------------------------------------------------------------------------


def test_next_session_id_starts_at_c_0001_when_no_sessions(tmp_path):
    assert next_session_id(_council_dir(tmp_path), "alpha") == "c-0001"


def test_next_session_id_increments_from_highest_existing(tmp_path):
    council_dir = _council_dir(tmp_path)
    create_session(council_dir, _fields())
    create_session(council_dir, _fields())

    assert next_session_id(council_dir, "alpha") == "c-0003"


def test_next_session_id_ignores_non_matching_files(tmp_path):
    council_dir = _council_dir(tmp_path)
    directory = sessions_dir(council_dir, "alpha")
    directory.mkdir(parents=True)
    (directory / "c-0001.json").write_text("{}", encoding="utf-8")
    (directory / "not-a-session.json").write_text("{}", encoding="utf-8")
    (directory / "c-garbage.json").write_text("{}", encoding="utf-8")

    assert next_session_id(council_dir, "alpha") == "c-0002"


def test_next_session_id_isolates_projects(tmp_path):
    council_dir = _council_dir(tmp_path)
    create_session(council_dir, _fields(project="alpha"))

    assert next_session_id(council_dir, "beta") == "c-0001"


# ---------------------------------------------------------------------------
# create_session / read_session
# ---------------------------------------------------------------------------


def test_create_session_assigns_id_and_created_at(tmp_path):
    session = create_session(_council_dir(tmp_path), _fields())

    assert session.id == "c-0001"
    assert session.created_at.endswith("Z")


def test_create_session_writes_readable_file(tmp_path):
    council_dir = _council_dir(tmp_path)
    created = create_session(council_dir, _fields())

    read_back = read_session(council_dir, "alpha", created.id)

    assert read_back == created


def test_create_session_missing_project_raises(tmp_path):
    fields = _fields()
    del fields["project"]

    with pytest.raises(CouncilSessionError):
        create_session(_council_dir(tmp_path), fields)


def test_create_session_invalid_topic_raises_council_session_error(tmp_path):
    with pytest.raises(CouncilSessionError):
        create_session(_council_dir(tmp_path), _fields(topic=""))


def test_create_session_invalid_status_raises_council_session_error(tmp_path):
    with pytest.raises(CouncilSessionError):
        create_session(_council_dir(tmp_path), _fields(status="bogus"))


def test_read_session_not_found_raises_council_session_error(tmp_path):
    with pytest.raises(CouncilSessionError):
        read_session(_council_dir(tmp_path), "alpha", "c-9999")


def test_read_session_corrupt_json_raises_council_session_error(tmp_path):
    council_dir = _council_dir(tmp_path)
    directory = sessions_dir(council_dir, "alpha")
    directory.mkdir(parents=True)
    (directory / "c-0001.json").write_text("not-json-at-all", encoding="utf-8")

    with pytest.raises(CouncilSessionError):
        read_session(council_dir, "alpha", "c-0001")


def test_read_session_invalid_content_raises_council_session_error(tmp_path):
    council_dir = _council_dir(tmp_path)
    directory = sessions_dir(council_dir, "alpha")
    directory.mkdir(parents=True)
    (directory / "c-0001.json").write_text(json.dumps({"id": "c-0001"}), encoding="utf-8")

    with pytest.raises(CouncilSessionError):
        read_session(council_dir, "alpha", "c-0001")


def test_create_session_id_sequence_survives_concurrent_creates(tmp_path):
    council_dir = _council_dir(tmp_path)
    results: list[CouncilSession] = []
    lock = threading.Lock()

    def _create():
        session = create_session(council_dir, _fields())
        with lock:
            results.append(session)

    threads = [threading.Thread(target=_create) for _ in range(15)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ids = sorted(session.id for session in results)
    assert ids == [f"c-{n:04d}" for n in range(1, 16)]


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_returns_newest_first(tmp_path):
    council_dir = _council_dir(tmp_path)
    first = create_session(council_dir, _fields(topic="first topic"))
    second = create_session(council_dir, _fields(topic="second topic"))
    third = create_session(council_dir, _fields(topic="third topic"))

    sessions = list_sessions(council_dir, "alpha")

    assert [s.id for s in sessions] == [third.id, second.id, first.id]


def test_list_sessions_respects_limit(tmp_path):
    council_dir = _council_dir(tmp_path)
    for i in range(5):
        create_session(council_dir, _fields(topic=f"topic {i}"))

    sessions = list_sessions(council_dir, "alpha", limit=2)

    assert len(sessions) == 2
    assert sessions[0].id == "c-0005"
    assert sessions[1].id == "c-0004"


def test_list_sessions_missing_directory_returns_empty(tmp_path):
    assert list_sessions(_council_dir(tmp_path), "does-not-exist") == []


def test_list_sessions_skips_corrupt_files(tmp_path):
    council_dir = _council_dir(tmp_path)
    good = create_session(council_dir, _fields())
    directory = sessions_dir(council_dir, "alpha")
    (directory / "c-9999.json").write_text("not-json", encoding="utf-8")

    sessions = list_sessions(council_dir, "alpha")

    assert [s.id for s in sessions] == [good.id]


def test_list_sessions_isolates_projects(tmp_path):
    council_dir = _council_dir(tmp_path)
    create_session(council_dir, _fields(project="alpha"))
    create_session(council_dir, _fields(project="beta"))

    alpha_sessions = list_sessions(council_dir, "alpha")
    beta_sessions = list_sessions(council_dir, "beta")

    assert len(alpha_sessions) == 1
    assert len(beta_sessions) == 1
    assert alpha_sessions[0].project == "alpha"
    assert beta_sessions[0].project == "beta"


# ---------------------------------------------------------------------------
# update_session
# ---------------------------------------------------------------------------


def test_update_session_persists_changes(tmp_path):
    council_dir = _council_dir(tmp_path)
    session = create_session(council_dir, _fields())

    updated = session.model_copy(update={"status": "running"})
    update_session(council_dir, updated)

    read_back = read_session(council_dir, "alpha", session.id)
    assert read_back.status == "running"


def test_update_session_adds_turns(tmp_path):
    council_dir = _council_dir(tmp_path)
    session = create_session(council_dir, _fields())

    updated = session.model_copy(
        update={"turns": [CouncilTurnState(round=1, member_id="claude", status="running")]}
    )
    update_session(council_dir, updated)

    read_back = read_session(council_dir, "alpha", session.id)
    assert len(read_back.turns) == 1
    assert read_back.turns[0].status == "running"


def test_update_session_is_atomic_no_partial_file_on_crash(tmp_path, monkeypatch):
    council_dir = _council_dir(tmp_path)
    session = create_session(council_dir, _fields())

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("persistent_memory.council.session.os.replace", _boom)

    with pytest.raises(OSError):
        update_session(council_dir, session.model_copy(update={"status": "running"}))

    read_back = read_session(council_dir, "alpha", session.id)
    assert read_back.status == "pending"


def test_update_session_with_reads_current_and_writes_mutation(tmp_path):
    council_dir = _council_dir(tmp_path)
    session = create_session(council_dir, _fields())

    result = update_session_with(
        council_dir, session.project, session.id, lambda current: current.model_copy(update={"status": "running"})
    )

    assert result.status == "running"
    assert read_session(council_dir, "alpha", session.id).status == "running"


def test_update_session_with_sees_concurrent_write_made_under_same_lock(tmp_path):
    council_dir = _council_dir(tmp_path)
    session = create_session(council_dir, _fields())
    update_session(council_dir, session.model_copy(update={"status": "cancelled"}))

    def _mutate(current):
        if current.status == "cancelled":
            return current
        return current.model_copy(update={"status": "running"})

    result = update_session_with(council_dir, session.project, session.id, _mutate)

    assert result.status == "cancelled"
    assert read_session(council_dir, "alpha", session.id).status == "cancelled"


# ---------------------------------------------------------------------------
# create_session with active_statuses (M4: TOCTOU-safe active-session check)
# ---------------------------------------------------------------------------


def test_create_session_with_active_statuses_allows_first_session(tmp_path):
    council_dir = _council_dir(tmp_path)
    session = create_session(council_dir, _fields(), active_statuses=ACTIVE_SESSION_STATUSES)

    assert session.status == "pending"


def test_create_session_with_active_statuses_rejects_second_active_session(tmp_path):
    council_dir = _council_dir(tmp_path)
    first = create_session(council_dir, _fields(), active_statuses=ACTIVE_SESSION_STATUSES)

    with pytest.raises(CouncilActiveSessionError) as exc_info:
        create_session(council_dir, _fields(topic="other"), active_statuses=ACTIVE_SESSION_STATUSES)

    assert exc_info.value.active_session_id == first.id


def test_create_session_with_active_statuses_allows_after_session_finishes(tmp_path):
    council_dir = _council_dir(tmp_path)
    first = create_session(council_dir, _fields(), active_statuses=ACTIVE_SESSION_STATUSES)
    update_session(council_dir, first.model_copy(update={"status": "converged"}))

    second = create_session(council_dir, _fields(topic="other"), active_statuses=ACTIVE_SESSION_STATUSES)

    assert second.id != first.id


def test_create_session_without_active_statuses_ignores_existing_active_session(tmp_path):
    council_dir = _council_dir(tmp_path)
    create_session(council_dir, _fields())

    second = create_session(council_dir, _fields(topic="other"))

    assert second.id == "c-0002"


def test_concurrent_updates_never_corrupt_file(tmp_path):
    council_dir = _council_dir(tmp_path)
    session = create_session(council_dir, _fields())
    update_count = 20

    def _update(i):
        turn = CouncilTurnState(round=1, member_id="claude", status="running")
        update_session(council_dir, session.model_copy(update={"turns": [turn], "status": "running"}))

    threads = [threading.Thread(target=_update, args=(i,)) for i in range(update_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    read_back = read_session(council_dir, "alpha", session.id)
    assert read_back.status == "running"
    assert len(read_back.turns) == 1
