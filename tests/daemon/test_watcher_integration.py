import time

import persistent_memory.daemon.services as services
from persistent_memory.daemon.watcher import HeartbeatCounter, RecordChangeHandler
from watchdog.observers import Observer

POLL_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.05
HEARTBEAT_THRESHOLD = 5


def _wait_until(predicate):
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return predicate()


def test_observer_embeds_and_survives_embed_failure(tmp_path, monkeypatch):
    watched = tmp_path / "decisions"
    watched.mkdir()
    embedded = []

    def boom(path, *, records_dir):
        embedded.append(str(path))
        raise RuntimeError("ollama down")

    monkeypatch.setattr(services, "embed_record", boom)

    consolidations = []
    handler = RecordChangeHandler(
        records_dir=tmp_path,
        heartbeat=HeartbeatCounter(threshold=HEARTBEAT_THRESHOLD),
        on_consolidate=lambda: consolidations.append(1),
    )
    observer = Observer()
    observer.schedule(handler, str(watched), recursive=False)
    observer.start()
    try:
        (watched / "D-0001.md").write_text("a", encoding="utf-8")
        assert _wait_until(lambda: len(embedded) >= 1)
        (watched / "D-0002.md").write_text("b", encoding="utf-8")
        assert _wait_until(lambda: len(embedded) >= 2)
        assert observer.is_alive()
    finally:
        observer.stop()
        observer.join()


def test_heartbeat_threshold_fires_consolidation_once(tmp_path, monkeypatch):
    watched = tmp_path / "decisions"
    watched.mkdir()
    monkeypatch.setattr(services, "embed_record", lambda path, *, records_dir: None)

    consolidations = []
    handler = RecordChangeHandler(
        records_dir=tmp_path,
        heartbeat=HeartbeatCounter(threshold=HEARTBEAT_THRESHOLD),
        on_consolidate=lambda: consolidations.append(1),
    )
    observer = Observer()
    observer.schedule(handler, str(watched), recursive=False)
    observer.start()
    try:
        for i in range(HEARTBEAT_THRESHOLD):
            record = watched / f"D-{i:04d}.md"
            record.write_text(f"content-{i}", encoding="utf-8")
            assert _wait_until(lambda i=i: handler.changes_seen >= i + 1)
        assert _wait_until(lambda: len(consolidations) == 1)
        time.sleep(0.3)
        assert len(consolidations) == 1
    finally:
        observer.stop()
        observer.join()
