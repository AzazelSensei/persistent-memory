import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app


def write_record(directory, rec_id, status):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec_id}.md").write_text(
        textwrap.dedent(f"""\
            ---
            id: {rec_id}
            type: decision
            status: {status}
            date: 2026-06-02
            project: alpha
            salience: 0.5
            ---
            ## Karar
            x
            """),
        encoding="utf-8",
    )


def test_index_renders_html(tmp_path):
    client = TestClient(create_app(records_dir=tmp_path))
    resp = client.get("/legacy")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "persistent-memory" in resp.text


def test_index_shows_pending_candidates(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "accepted")
    write_record(tmp_path / "decisions", "D-0002", "proposed")
    client = TestClient(create_app(records_dir=tmp_path))
    html = client.get("/legacy").text
    assert "D-0002" in html
    assert "1" in html
