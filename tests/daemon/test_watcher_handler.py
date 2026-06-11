from types import SimpleNamespace

import persistent_memory.daemon.services as services
from persistent_memory.daemon.watcher import HeartbeatCounter, RecordChangeHandler


def test_heartbeat_triggers_every_fifth():
    hb = HeartbeatCounter(threshold=5)
    fired = [hb.tick() for _ in range(12)]
    assert fired == [False, False, False, False, True,
                     False, False, False, False, True,
                     False, False]


def test_handler_embeds_on_md_change(tmp_path, monkeypatch):
    embedded = []
    monkeypatch.setattr(services, "embed_record", lambda path, *, records_dir: embedded.append(str(path)))
    handler = RecordChangeHandler(records_dir=tmp_path)
    md = tmp_path / "decisions" / "D-0001.md"
    handler.on_modified(SimpleNamespace(is_directory=False, src_path=str(md)))
    assert embedded == [str(md)]
    assert handler.changes_seen == 1


def test_handler_ignores_non_markdown(tmp_path, monkeypatch):
    embedded = []
    monkeypatch.setattr(services, "embed_record", lambda path, *, records_dir: embedded.append(str(path)))
    handler = RecordChangeHandler(records_dir=tmp_path)
    handler.on_modified(SimpleNamespace(is_directory=False, src_path=str(tmp_path / "x.txt")))
    assert embedded == []


def test_handler_ignores_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "embed_record", lambda path, *, records_dir: (_ for _ in ()).throw(AssertionError("should not embed")))
    handler = RecordChangeHandler(records_dir=tmp_path)
    handler.on_modified(SimpleNamespace(is_directory=True, src_path=str(tmp_path / "decisions")))


def test_handler_swallows_embed_errors(tmp_path, monkeypatch):
    def boom(path, *, records_dir):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(services, "embed_record", boom)
    fired = []
    handler = RecordChangeHandler(
        records_dir=tmp_path,
        heartbeat=HeartbeatCounter(threshold=1),
        on_consolidate=lambda: fired.append(1),
    )
    md = tmp_path / "decisions" / "D-0001.md"
    handler.on_modified(SimpleNamespace(is_directory=False, src_path=str(md)))
    assert handler.changes_seen == 1
    assert fired == [1]


def test_handler_fires_consolidate_at_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "embed_record", lambda path, *, records_dir: None)
    fired = []
    handler = RecordChangeHandler(
        records_dir=tmp_path,
        heartbeat=HeartbeatCounter(threshold=3),
        on_consolidate=lambda: fired.append(1),
    )
    for i in range(3):
        md = tmp_path / "decisions" / f"D-{i:04d}.md"
        handler.on_modified(SimpleNamespace(is_directory=False, src_path=str(md)))
    assert fired == [1]


def test_embed_failure_is_logged(tmp_path, monkeypatch, caplog):
    import logging
    from types import SimpleNamespace as NS

    def boom(path, *, records_dir):
        raise RuntimeError("embed patladi")

    monkeypatch.setattr(services, "embed_record", boom)
    handler = RecordChangeHandler(records_dir=tmp_path)
    md = tmp_path / "decisions" / "D-0001.md"
    with caplog.at_level(logging.WARNING):
        handler.on_modified(NS(is_directory=False, src_path=str(md)))
    assert "embed" in caplog.text.lower()


def test_handler_embeds_on_md_rename(tmp_path, monkeypatch):
    embedded = []
    monkeypatch.setattr(services, "embed_record", lambda path, *, records_dir: embedded.append(str(path)))
    handler = RecordChangeHandler(records_dir=tmp_path)
    tmp_file = tmp_path / "decisions" / "x.tmp"
    md = tmp_path / "decisions" / "D-0001.md"
    handler.on_moved(SimpleNamespace(is_directory=False, src_path=str(tmp_file), dest_path=str(md)))
    assert embedded == [str(md)]
