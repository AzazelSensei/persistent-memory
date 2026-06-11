import sqlite3

import pytest

from persistent_memory.graph_ingest import ClaudeMemDbError, open_claudemem_db


def _build_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE observations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            text TEXT, type TEXT NOT NULL, title TEXT, subtitle TEXT,
            facts TEXT, narrative TEXT, concepts TEXT,
            files_read TEXT, files_modified TEXT,
            prompt_number INTEGER, discovery_tokens INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, created_at_epoch INTEGER NOT NULL,
            content_hash TEXT
        );
        CREATE TABLE user_prompts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_session_id TEXT NOT NULL,
            prompt_number INTEGER NOT NULL,
            prompt_text TEXT NOT NULL,
            created_at TEXT NOT NULL, created_at_epoch INTEGER NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def memdb(tmp_path):
    path = tmp_path / "claude-mem.db"
    _build_db(str(path))
    return path


def test_open_db_reads(memdb):
    conn = open_claudemem_db(str(memdb))
    rows = conn.execute("SELECT count(*) FROM observations").fetchone()
    assert rows[0] == 0
    conn.close()


def test_open_db_blocks_writes(memdb):
    conn = open_claudemem_db(str(memdb))
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute(
            "INSERT INTO observations(memory_session_id, project, type, created_at, created_at_epoch) "
            "VALUES('s','p','x','2026-06-02',1)"
        )
    conn.close()


def test_open_db_missing_raises(tmp_path):
    with pytest.raises(ClaudeMemDbError, match="not found"):
        open_claudemem_db(str(tmp_path / "yok.db"))


def test_open_db_default_is_not_immutable():
    import inspect

    from persistent_memory.graph_ingest import RO_URI_LIVE_TEMPLATE

    default = inspect.signature(open_claudemem_db).parameters["is_immutable"].default
    assert default is False
    assert "immutable=1" not in RO_URI_LIVE_TEMPLATE


def test_open_db_default_blocks_writes(memdb):
    conn = open_claudemem_db(str(memdb))
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute(
            "INSERT INTO observations(memory_session_id, project, type, created_at, created_at_epoch) "
            "VALUES('s','p','x','2026-06-02',1)"
        )
    conn.close()


from persistent_memory.graph_ingest import pull_observations


def _insert_obs(path, **kw):
    conn = sqlite3.connect(path)
    cols = ("memory_session_id", "project", "text", "type", "title", "subtitle",
            "facts", "narrative", "concepts", "files_read", "files_modified",
            "prompt_number", "created_at", "created_at_epoch", "content_hash")
    vals = [kw.get(c) for c in cols]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(f"INSERT INTO observations({','.join(cols)}) VALUES({placeholders})", vals)
    conn.commit()
    conn.close()


def test_pull_observations_filters_project(memdb):
    _insert_obs(str(memdb), memory_session_id="s1", project="project-alpha", type="decision",
                title="A", narrative="n1", created_at="2026-06-01", created_at_epoch=100)
    _insert_obs(str(memdb), memory_session_id="s2", project="project-beta", type="decision",
                title="B", narrative="n2", created_at="2026-06-01", created_at_epoch=101)
    rows = pull_observations(str(memdb), project="project-alpha")
    assert len(rows) == 1
    assert rows[0]["title"] == "A"
    assert rows[0]["project"] == "project-alpha"


def test_pull_observations_since_epoch(memdb):
    _insert_obs(str(memdb), memory_session_id="s1", project="project-alpha", type="x",
                title="old", created_at="2026-05-01", created_at_epoch=50)
    _insert_obs(str(memdb), memory_session_id="s1", project="project-alpha", type="x",
                title="new", created_at="2026-06-01", created_at_epoch=150)
    rows = pull_observations(str(memdb), project="project-alpha", since_epoch=100)
    assert [r["title"] for r in rows] == ["new"]


def test_pull_observations_orders_by_epoch_asc(memdb):
    _insert_obs(str(memdb), memory_session_id="s1", project="p", type="x",
                title="second", created_at="2026-06-02", created_at_epoch=200)
    _insert_obs(str(memdb), memory_session_id="s1", project="p", type="x",
                title="first", created_at="2026-06-01", created_at_epoch=100)
    rows = pull_observations(str(memdb), project="p")
    assert [r["title"] for r in rows] == ["first", "second"]


from persistent_memory.graph_ingest import pull_user_prompts


def _insert_session(path, content_session_id, project):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sdk_sessions("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, content_session_id TEXT UNIQUE NOT NULL,"
        "memory_session_id TEXT, project TEXT NOT NULL, started_at TEXT, started_at_epoch INTEGER,"
        "status TEXT DEFAULT 'active')"
    )
    conn.execute(
        "INSERT INTO sdk_sessions(content_session_id, project, started_at, started_at_epoch) VALUES(?,?,?,?)",
        (content_session_id, project, "2026-06-01", 1),
    )
    conn.commit()
    conn.close()


def _insert_prompt(path, **kw):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO user_prompts(content_session_id, prompt_number, prompt_text, created_at, created_at_epoch) "
        "VALUES(?,?,?,?,?)",
        (kw["content_session_id"], kw["prompt_number"], kw["prompt_text"], kw["created_at"], kw["created_at_epoch"]),
    )
    conn.commit()
    conn.close()


def test_pull_user_prompts_filters_project(memdb):
    _insert_session(str(memdb), "cs1", "project-alpha")
    _insert_session(str(memdb), "cs2", "project-beta")
    _insert_prompt(str(memdb), content_session_id="cs1", prompt_number=1, prompt_text="hello", created_at="2026-06-01", created_at_epoch=100)
    _insert_prompt(str(memdb), content_session_id="cs2", prompt_number=1, prompt_text="other", created_at="2026-06-01", created_at_epoch=101)
    rows = pull_user_prompts(str(memdb), project="project-alpha")
    assert len(rows) == 1
    assert rows[0]["prompt_text"] == "hello"


def test_pull_user_prompts_since_epoch(memdb):
    _insert_session(str(memdb), "cs1", "project-alpha")
    _insert_prompt(str(memdb), content_session_id="cs1", prompt_number=1, prompt_text="old", created_at="2026-05-01", created_at_epoch=50)
    _insert_prompt(str(memdb), content_session_id="cs1", prompt_number=2, prompt_text="new", created_at="2026-06-01", created_at_epoch=150)
    rows = pull_user_prompts(str(memdb), project="project-alpha", since_epoch=100)
    assert [r["prompt_text"] for r in rows] == ["new"]


import json

import frontmatter

from persistent_memory.graph_ingest import export_observation_to_md


def test_export_observation_writes_frontmatter(memdb, tmp_path):
    _insert_obs(str(memdb), memory_session_id="s9", project="project-alpha", type="decision",
                title="Postgres secildi", subtitle="db",
                facts=json.dumps(["fact-a", "fact-b"]),
                narrative="MySQL yerine Postgres tercih edildi.",
                concepts=json.dumps(["veritabani", "postgres"]),
                created_at="2026-06-02", created_at_epoch=1000)
    row = pull_observations(str(memdb), project="project-alpha")[0]
    out_dir = tmp_path / "observations"
    path = export_observation_to_md(row, str(out_dir))
    assert path.endswith("obs-1.md")
    post = frontmatter.load(path)
    assert post["type"] == "observation"
    assert post["source"] == "claude-mem"
    assert post["source_id"] == 1
    assert post["session"] == "s9"
    assert post["project"] == "project-alpha"
    assert post["created_at"] == "2026-06-02"
    body = post.content
    assert "MySQL yerine Postgres" in body
    assert "fact-a" in body
    assert "veritabani" in body


def test_export_observation_handles_null_json(memdb, tmp_path):
    _insert_obs(str(memdb), memory_session_id="s1", project="p", type="x",
                title="t", narrative="just narrative",
                facts=None, concepts=None,
                created_at="2026-06-02", created_at_epoch=1)
    row = pull_observations(str(memdb), project="p")[0]
    path = export_observation_to_md(row, str(tmp_path))
    post = frontmatter.load(path)
    assert post.content.strip().endswith("just narrative") or "just narrative" in post.content


def test_export_observation_bad_json_raises(memdb, tmp_path):
    _insert_obs(str(memdb), memory_session_id="s1", project="p", type="x",
                title="t", narrative="n", facts="{not json", created_at="2026-06-02", created_at_epoch=1)
    row = pull_observations(str(memdb), project="p")[0]
    with pytest.raises(ClaudeMemDbError, match="invalid JSON"):
        export_observation_to_md(row, str(tmp_path))


from persistent_memory.graph_ingest import DedupLedger


def test_dedup_ledger_new_id_seen(tmp_path):
    ledger = DedupLedger(str(tmp_path / "exported.json"))
    assert ledger.is_exported(7) is False
    ledger.mark_exported(7)
    assert ledger.is_exported(7) is True


def test_dedup_ledger_persists(tmp_path):
    ledger_path = tmp_path / "exported.json"
    first = DedupLedger(str(ledger_path))
    first.mark_exported(1)
    first.mark_exported(2)
    first.save()
    second = DedupLedger(str(ledger_path))
    assert second.is_exported(1) is True
    assert second.is_exported(2) is True
    assert second.is_exported(3) is False


def test_dedup_ledger_missing_file_starts_empty(tmp_path):
    ledger = DedupLedger(str(tmp_path / "yok.json"))
    assert ledger.is_exported(1) is False


from persistent_memory.graph_ingest import export_observations


def test_export_observations_skips_already_exported(memdb, tmp_path):
    _insert_obs(str(memdb), memory_session_id="s1", project="project-alpha", type="x",
                title="one", narrative="n", created_at="2026-06-01", created_at_epoch=10)
    _insert_obs(str(memdb), memory_session_id="s1", project="project-alpha", type="x",
                title="two", narrative="n", created_at="2026-06-02", created_at_epoch=20)
    out_dir = tmp_path / "observations"
    ledger_path = tmp_path / "exported.json"
    written = export_observations(str(memdb), project="project-alpha",
                                  out_dir=str(out_dir), ledger_path=str(ledger_path))
    assert len(written) == 2
    again = export_observations(str(memdb), project="project-alpha",
                                out_dir=str(out_dir), ledger_path=str(ledger_path))
    assert again == []


def test_export_observations_skips_empty_observation(memdb, tmp_path):
    _insert_obs(str(memdb), memory_session_id="s1", project="project-alpha", type="x",
                title=None, narrative=None, text=None,
                facts=None, concepts=None,
                created_at="2026-06-01", created_at_epoch=10)
    out_dir = tmp_path / "observations"
    ledger_path = tmp_path / "exported.json"
    written = export_observations(str(memdb), project="project-alpha",
                                  out_dir=str(out_dir), ledger_path=str(ledger_path))
    assert written == []
    assert not (out_dir / "obs-1.md").exists()


def test_export_observations_only_target_project(memdb, tmp_path):
    _insert_obs(str(memdb), memory_session_id="s1", project="project-alpha", type="x",
                title="keep", narrative="n", created_at="2026-06-01", created_at_epoch=10)
    _insert_obs(str(memdb), memory_session_id="s2", project="other", type="x",
                title="drop", narrative="n", created_at="2026-06-01", created_at_epoch=11)
    out_dir = tmp_path / "observations"
    written = export_observations(str(memdb), project="project-alpha",
                                  out_dir=str(out_dir), ledger_path=str(tmp_path / "l.json"))
    assert len(written) == 1
    assert written[0].endswith("obs-1.md")


from persistent_memory.graph_ingest import build_unified_corpus


def _touch_md(d, name, text="x"):
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_build_unified_corpus_links_all_sources(tmp_path):
    decisions = tmp_path / "docs" / "decisions"
    lessons = tmp_path / "docs" / "lessons"
    observations = tmp_path / ".pm-corpus" / "observations"
    _touch_md(decisions, "0001-postgres.md")
    _touch_md(lessons, "0001-timeout.md")
    _touch_md(observations, "obs-7.md")
    corpus_root = tmp_path / ".pm-corpus" / "unified"
    linked = build_unified_corpus(
        corpus_root=str(corpus_root),
        decisions_dir=str(decisions),
        lessons_dir=str(lessons),
        observations_dir=str(observations),
    )
    assert len(linked) == 3
    names = sorted(p.name for p in corpus_root.iterdir())
    assert names == ["0001-postgres.md", "0001-timeout.md", "obs-7.md"]
    assert all((corpus_root / n).is_symlink() for n in names)


def test_build_unified_corpus_is_idempotent(tmp_path):
    decisions = tmp_path / "docs" / "decisions"
    observations = tmp_path / ".pm-corpus" / "observations"
    _touch_md(decisions, "0001-a.md")
    _touch_md(observations, "obs-1.md")
    corpus_root = tmp_path / "unified"
    build_unified_corpus(corpus_root=str(corpus_root), decisions_dir=str(decisions),
                         lessons_dir=str(tmp_path / "none-lessons"), observations_dir=str(observations))
    (observations / "obs-1.md").unlink()
    linked = build_unified_corpus(corpus_root=str(corpus_root), decisions_dir=str(decisions),
                                  lessons_dir=str(tmp_path / "none-lessons"), observations_dir=str(observations))
    names = sorted(p.name for p in corpus_root.iterdir())
    assert names == ["0001-a.md"]
    assert len(linked) == 1


def test_build_unified_corpus_missing_dir_ok(tmp_path):
    decisions = tmp_path / "docs" / "decisions"
    _touch_md(decisions, "0001-a.md")
    corpus_root = tmp_path / "unified"
    linked = build_unified_corpus(corpus_root=str(corpus_root), decisions_dir=str(decisions),
                                  lessons_dir=str(tmp_path / "missing-l"),
                                  observations_dir=str(tmp_path / "missing-o"))
    assert len(linked) == 1
