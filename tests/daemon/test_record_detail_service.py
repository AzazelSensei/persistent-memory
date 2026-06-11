import textwrap

import pytest

from persistent_memory.daemon import services


def write_full_record(directory, rec_id, rec_type, *, status="proposed", project="alpha",
                      body=None, supersedes=None, superseded_by=None, tags=None, salience=0.5,
                      date="2026-06-02"):
    directory.mkdir(parents=True, exist_ok=True)
    body = body or "# Baslik\n\n## Karar\ngovde metni\n"
    tags = tags or []
    supersedes = supersedes or []
    superseded_by = superseded_by or []
    front = textwrap.dedent(f"""\
        ---
        id: {rec_id}
        type: {rec_type}
        status: {status}
        date: '{date}'
        project: {project}
        provenance:
          session: sess-1
          cwd: /tmp/work
          agent: claude-opus-4-8
        tags: {tags}
        supersedes: {supersedes}
        superseded-by: {superseded_by}
        salience: {salience}
        ---
        """)
    (directory / f"{rec_id}.md").write_text(front + body, encoding="utf-8")


def test_record_detail_extracts_title_and_sections(tmp_path):
    body = (
        "# Postgres yerine SQLite secildi\n\n"
        "## Baglam / Problem\n"
        "Kucuk olcekli yerel hafiza.\n\n"
        "## Karar\n"
        "SQLite kullan.\n\n"
        "## Gerekce\n"
        "Operasyonel basitlik.\n"
    )
    write_full_record(tmp_path / "decisions", "D-0001", "decision", body=body, tags=["db"])
    detail = services.record_detail(tmp_path, "D-0001")
    assert detail["id"] == "D-0001"
    assert detail["title"] == "Postgres yerine SQLite secildi"
    assert detail["type"] == "decision"
    assert detail["status"] == "proposed"
    assert detail["project"] == "alpha"
    headings = [s["heading"] for s in detail["sections"]]
    assert headings == ["Baglam / Problem", "Karar", "Gerekce"]
    karar = next(s for s in detail["sections"] if s["heading"] == "Karar")
    assert "SQLite kullan." in karar["text"]
    assert detail["tags"] == ["db"]
    assert detail["provenance"]["agent"] == "claude-opus-4-8"
    assert detail["salience"] == 0.5


def test_record_detail_resolves_supersession_chain_titles(tmp_path):
    write_full_record(
        tmp_path / "decisions", "D-0001", "decision",
        status="superseded", superseded_by=["D-0002"],
        body="# Eski karar\n\n## Karar\neski\n",
    )
    write_full_record(
        tmp_path / "decisions", "D-0002", "decision",
        supersedes=["D-0001"],
        body="# Yeni karar\n\n## Karar\nyeni\n",
    )
    detail = services.record_detail(tmp_path, "D-0001")
    assert detail["superseded_by"] == [{"id": "D-0002", "title": "Yeni karar"}]
    forward = services.record_detail(tmp_path, "D-0002")
    assert forward["supersedes"] == [{"id": "D-0001", "title": "Eski karar"}]


def test_record_detail_unknown_id_raises(tmp_path):
    (tmp_path / "decisions").mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        services.record_detail(tmp_path, "D-9999")


def test_record_detail_missing_title_falls_back_to_id(tmp_path):
    write_full_record(
        tmp_path / "lessons", "L-0001", "lesson",
        body="## Ne oldu\nbir sey oldu\n",
    )
    detail = services.record_detail(tmp_path, "L-0001")
    assert detail["title"] == "L-0001"
