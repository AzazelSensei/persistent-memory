import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.token import load_or_create_token


def write_record(directory, rec_id, rec_type, status, *, title="Baslik", project="alpha"):
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


def test_home_shows_stat_cards(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "accepted")
    write_record(tmp_path / "decisions", "D-0002", "decision", "proposed")
    write_record(tmp_path / "lessons", "L-0001", "lesson", "accepted")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/legacy").text
    assert "Decisions" in html
    assert "Lessons" in html
    assert "Pending" in html
    assert "Projects" in html


def test_home_pending_queue_shows_title_and_actions(tmp_path):
    write_record(tmp_path / "decisions", "D-0002", "decision", "proposed",
                 title="Bekleyen karar basligi")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/legacy").text
    assert "Bekleyen karar basligi" in html
    assert "/records/D-0002" in html
    assert "Approve" in html
    assert load_or_create_token(tmp_path) in html


def test_home_escapes_title(tmp_path):
    write_record(tmp_path / "decisions", "D-0002", "decision", "proposed",
                 title="<img src=x onerror=alert(1)>")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/legacy").text
    assert "<img src=x onerror=alert(1)>" not in html


def test_home_no_pending_shows_empty_state(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "accepted")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/legacy").text
    assert "Pending" in html
