"""Tests for the live record notification SSE endpoint."""

import json
import threading

import pytest
from starlette.testclient import TestClient

import persistent_memory.daemon.live as live
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig

WRITE_DELAY_SECONDS = 0.08
STREAM_TEST_TIMEOUT_SECONDS = 5.0


def _run_with_timeout(fn, timeout=STREAM_TEST_TIMEOUT_SECONDS):
    """Run `fn` in a background thread and enforce a hard wall-clock limit.

    `TestClient.stream(...)` blocks the calling thread until the SSE
    generator terminates, so a regression in the stream's termination
    logic (the MAX_STREAM_SECONDS guard, heartbeat bookkeeping, etc.)
    would otherwise hang the test process instead of failing it. Running
    the blocking work on a daemon thread lets us fail fast with a clear
    message when that happens, rather than the test suite stalling.
    """
    outcome: dict = {}

    def _target():
        try:
            outcome["value"] = fn()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        pytest.fail(
            f"stream did not terminate within {timeout}s - the SSE generator "
            "likely never closes (regression in the termination/heartbeat guard)"
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _write_record(directory, record_id, *, project="myapp", status="proposed", date="2026-01-01", title=None):
    directory.mkdir(parents=True, exist_ok=True)
    record_type = "decision" if record_id.startswith("D-") else "lesson"
    heading = title or f"Title for {record_id}"
    body = (
        "---\n"
        f"id: {record_id}\n"
        f"type: {record_type}\n"
        f"status: {status}\n"
        f"date: '{date}'\n"
        f"project: {project}\n"
        "---\n"
        f"# {heading}\n\nbody text\n"
    )
    (directory / f"{record_id}.md").write_text(body, encoding="utf-8")


def _write_record_after_delay(directory, record_id, delay=WRITE_DELAY_SECONDS, **kwargs):
    """Write the record from a background thread after `delay` seconds.

    The SSE generator only takes its initial "known ids" snapshot once the
    response body actually starts being iterated (TestClient drives the
    async generator lazily) — writing synchronously before `iter_lines()`
    would land inside that snapshot instead of after it, so this defers the
    write to land mid-poll-loop, matching a record that genuinely appears
    while a client is already connected.
    """
    timer = threading.Timer(delay, _write_record, args=(directory, record_id), kwargs=kwargs)
    timer.start()
    return timer


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
    monkeypatch.setattr(live, "POLL_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(live, "HEARTBEAT_SECONDS", 30)
    monkeypatch.setattr(live, "MAX_STREAM_SECONDS", 0.5)
    yield


def test_stream_response_is_event_stream_content_type(tmp_path):
    client = _client(tmp_path)

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return resp.status_code, resp.headers["content-type"]

    status_code, content_type = _run_with_timeout(_run)
    assert status_code == 200
    assert content_type.startswith("text/event-stream")


def test_stream_no_token_required(tmp_path):
    client = _client(tmp_path)

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return resp.status_code

    assert _run_with_timeout(_run) == 200


def test_stream_does_not_replay_preexisting_records_without_since(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    _write_record(cfg.decisions_dir, "D-0001")
    client = _client(tmp_path)

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return list(resp.iter_lines())

    lines = _run_with_timeout(_run)
    events = [line for line in lines if line.startswith("event: record")]
    assert events == []


def test_stream_emits_new_decision_record_while_connected(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    cfg.decisions_dir.mkdir(parents=True, exist_ok=True)
    client = _client(tmp_path)
    _write_record_after_delay(cfg.decisions_dir, "D-0001", title="Ship the thing")

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return _collect_sse_until(
                resp.iter_lines(), lambda event, data: event == "record" and data.get("id") == "D-0001"
            )

    events = _run_with_timeout(_run)
    assert events, "expected a record event"
    record = events[-1][1]
    assert record["id"] == "D-0001"
    assert record["type"] == "decision"
    assert record["title"] == "Ship the thing"
    assert record["project"] == "myapp"
    assert record["status"] == "proposed"
    assert record["date"] == "2026-01-01"


def test_stream_emits_new_lesson_record_while_connected(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    cfg.lessons_dir.mkdir(parents=True, exist_ok=True)
    client = _client(tmp_path)
    _write_record_after_delay(cfg.lessons_dir, "L-0001", title="Don't do that again")

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return _collect_sse_until(
                resp.iter_lines(), lambda event, data: event == "record" and data.get("id") == "L-0001"
            )

    events = _run_with_timeout(_run)
    assert events[-1][1]["type"] == "lesson"


def test_stream_since_catches_record_written_before_connect(tmp_path):
    """The client's last-known watermark can be older than a file that's
    already on disk before the stream even opens — the stream must still
    surface it as new, matching a reconnect/catch-up flow."""
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    _write_record(cfg.decisions_dir, "D-0005", title="Written before connect")
    client = _client(tmp_path)

    def _run():
        with client.stream("GET", "/api/stream/records", params={"since": "D-0001"}) as resp:
            return _collect_sse_until(
                resp.iter_lines(), lambda event, data: event == "record" and data.get("id") == "D-0005"
            )

    events = _run_with_timeout(_run)
    assert events, "expected the pre-existing record to be replayed via since"
    assert events[-1][1]["id"] == "D-0005"


def test_stream_since_does_not_replay_records_at_or_below_watermark(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    _write_record(cfg.decisions_dir, "D-0001")
    client = _client(tmp_path)

    def _run():
        with client.stream("GET", "/api/stream/records", params={"since": "D-0001"}) as resp:
            return list(resp.iter_lines())

    lines = _run_with_timeout(_run)
    events = [line for line in lines if line.startswith("event: record")]
    assert events == []


def test_stream_project_filter_excludes_other_projects(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    cfg.decisions_dir.mkdir(parents=True, exist_ok=True)
    client = _client(tmp_path)
    _write_record_after_delay(cfg.decisions_dir, "D-0001", project="myapp")
    _write_record_after_delay(cfg.decisions_dir, "D-0002", project="other")

    def _run():
        with client.stream("GET", "/api/stream/records", params={"project": "other"}) as resp:
            return _collect_sse_until(
                resp.iter_lines(), lambda event, data: event == "record" and data.get("id") == "D-0002"
            )

    events = _run_with_timeout(_run)
    ids = [data.get("id") for event, data in events if event == "record"]
    assert "D-0002" in ids
    assert "D-0001" not in ids


def test_stream_emits_ping_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(live, "MAX_STREAM_SECONDS", 0.3)
    client = _client(tmp_path)

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return _collect_sse_until(resp.iter_lines(), lambda event, data: event == "ping")

    events = _run_with_timeout(_run)
    assert events, "expected a ping heartbeat event"
    assert events[-1][0] == "ping"
    assert "ts" in events[-1][1]


def test_stream_closes_after_max_stream_seconds(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "MAX_STREAM_SECONDS", 0.05)
    monkeypatch.setattr(live, "HEARTBEAT_SECONDS", 30)
    client = _client(tmp_path)

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return list(resp.iter_lines())

    assert _run_with_timeout(_run) == []


def test_stream_skips_corrupt_frontmatter_file_without_dropping_stream(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    cfg.decisions_dir.mkdir(parents=True, exist_ok=True)
    client = _client(tmp_path)
    threading.Timer(
        WRITE_DELAY_SECONDS,
        (cfg.decisions_dir / "D-0001.md").write_text,
        args=("---\nid: [broken\ntype: decision\n---\n# Title\nbody\n",),
        kwargs={"encoding": "utf-8"},
    ).start()
    _write_record_after_delay(cfg.decisions_dir, "D-0002", title="Comes after the broken file")

    def _run():
        with client.stream("GET", "/api/stream/records") as resp:
            return _collect_sse_until(
                resp.iter_lines(), lambda event, data: event == "record" and data.get("id") == "D-0002"
            )

    events = _run_with_timeout(_run)
    ids = [data.get("id") for event, data in events if event == "record"]
    assert "D-0002" in ids
    assert "D-0001" not in ids
