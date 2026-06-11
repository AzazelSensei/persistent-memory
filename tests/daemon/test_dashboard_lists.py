import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app


def write(directory, rec_id, rec_type, date, status="accepted", superseded_by=None):
    directory.mkdir(parents=True, exist_ok=True)
    sb = superseded_by or []
    (directory / f"{rec_id}.md").write_text(
        textwrap.dedent(f"""\
            ---
            id: {rec_id}
            type: {rec_type}
            status: {status}
            date: {date}
            project: alpha
            salience: 0.5
            superseded-by: {sb}
            ---
            ## Karar
            x
            """),
        encoding="utf-8",
    )


def test_decisions_page_shows_chain(tmp_path):
    write(tmp_path / "decisions", "D-0001", "decision", "2026-01-01",
          status="superseded", superseded_by=["D-0002"])
    write(tmp_path / "decisions", "D-0002", "decision", "2026-02-01")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/decisions").text
    assert "D-0001" in html and "D-0002" in html
    assert "superseded" in html


def test_lessons_page(tmp_path):
    write(tmp_path / "lessons", "L-0001", "lesson", "2026-03-01")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/lessons").text
    assert "L-0001" in html


def test_timeline_sorted_desc(tmp_path):
    write(tmp_path / "decisions", "D-0001", "decision", "2026-01-01")
    write(tmp_path / "lessons", "L-0001", "lesson", "2026-05-01")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/timeline").text
    assert html.index("L-0001") < html.index("D-0001")
