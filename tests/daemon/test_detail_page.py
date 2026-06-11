import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.token import load_or_create_token


def write_record(directory, rec_id, rec_type, status, *, body, project="alpha"):
    directory.mkdir(parents=True, exist_ok=True)
    front = textwrap.dedent(f"""\
        ---
        id: {rec_id}
        type: {rec_type}
        status: {status}
        date: '2026-06-02'
        project: {project}
        provenance:
          session: s
          cwd: /tmp
          agent: claude-opus-4-8
        tags: []
        supersedes: []
        superseded-by: []
        salience: 0.5
        ---
        """)
    (directory / f"{rec_id}.md").write_text(front + body, encoding="utf-8")


def test_detail_page_shows_title_and_sections(tmp_path):
    write_record(
        tmp_path / "decisions", "D-0001", "decision", "proposed",
        body="# SQLite secildi\n\n## Karar\nSQLite kullan\n\n## Gerekce\nbasitlik\n",
    )
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/records/D-0001").text
    assert "SQLite secildi" in html
    assert "Karar" in html
    assert "SQLite kullan" in html
    assert "Gerekce" in html


def test_detail_page_proposed_shows_approve_control(tmp_path):
    write_record(
        tmp_path / "decisions", "D-0001", "decision", "proposed",
        body="# Baslik\n\n## Karar\nx\n",
    )
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/records/D-0001").text
    assert "Approve" in html
    assert "Reject" in html
    assert load_or_create_token(tmp_path) in html


def test_detail_page_accepted_hides_actions(tmp_path):
    write_record(
        tmp_path / "decisions", "D-0001", "decision", "accepted",
        body="# Baslik\n\n## Karar\nx\n",
    )
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/records/D-0001").text
    assert "accepted" in html


def test_detail_page_unknown_id_returns_404(tmp_path):
    (tmp_path / "decisions").mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(records_dir=tmp_path))
    assert client.get("/records/D-9999").status_code == 404


def test_detail_page_malformed_id_returns_422(tmp_path):
    client = TestClient(create_app(records_dir=tmp_path))
    assert client.get("/records/not-an-id").status_code == 422


def test_detail_page_escapes_record_content(tmp_path):
    write_record(
        tmp_path / "decisions", "D-0001", "decision", "proposed",
        body="# Baslik\n\n## Karar\n<script>alert(1)</script>\n",
    )
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/records/D-0001").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_detail_page_shows_supersession_links(tmp_path):
    write_record(
        tmp_path / "decisions", "D-0001", "decision", "superseded",
        body="# Eski\n\n## Karar\neski\n",
    )
    write_record(
        tmp_path / "decisions", "D-0002", "decision", "accepted",
        body="# Yeni\n\n## Karar\nyeni\n",
    )
    superseded = (tmp_path / "decisions" / "D-0001.md").read_text(encoding="utf-8")
    (tmp_path / "decisions" / "D-0001.md").write_text(
        superseded.replace("superseded-by: []", "superseded-by: ['D-0002']"),
        encoding="utf-8",
    )
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/records/D-0001").text
    assert "D-0002" in html
    assert "/records/D-0002" in html
