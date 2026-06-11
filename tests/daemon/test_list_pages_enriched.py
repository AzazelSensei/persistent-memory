import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.token import load_or_create_token


def write_record(directory, rec_id, rec_type, status, *, title, project="alpha"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec_id}.md").write_text(
        textwrap.dedent(f"""\
            ---
            id: {rec_id}
            type: {rec_type}
            status: {status}
            date: '2026-06-02'
            project: {project}
            provenance:
              session: s
              cwd: /tmp
              agent: a
            tags: []
            supersedes: []
            superseded-by: []
            salience: 0.5
            ---
            # {title}

            ## Karar
            govde
            """),
        encoding="utf-8",
    )


def test_decisions_list_shows_titles_and_detail_links(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "accepted",
                 title="Onemli karar basligi")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/decisions").text
    assert "Onemli karar basligi" in html
    assert "/records/D-0001" in html


def test_decisions_list_shows_status_badge(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed",
                 title="Bekleyen karar")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/decisions").text
    assert "proposed" in html


def test_decisions_list_proposed_has_inline_approve(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed",
                 title="Bekleyen karar")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/decisions").text
    assert "Approve" in html
    assert load_or_create_token(tmp_path) in html


def test_lessons_list_shows_titles(tmp_path):
    write_record(tmp_path / "lessons", "L-0001", "lesson", "accepted",
                 title="Onemli ders")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/lessons").text
    assert "Onemli ders" in html
    assert "/records/L-0001" in html


def test_decisions_list_escapes_title(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "accepted",
                 title="<script>alert(1)</script>")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/decisions").text
    assert "<script>alert(1)</script>" not in html
