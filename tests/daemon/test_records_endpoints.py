import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app


def write_record(directory, rec_id, status):
    directory.mkdir(parents=True, exist_ok=True)
    body = textwrap.dedent(f"""\
        ---
        id: {rec_id}
        type: decision
        status: {status}
        date: 2026-06-02
        project: alpha
        salience: 0.5
        ---
        ## Karar
        deneme
        """)
    (directory / f"{rec_id}.md").write_text(body, encoding="utf-8")


def make_client(tmp_path):
    return TestClient(create_app(records_dir=tmp_path))


def test_list_records_returns_all(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "accepted")
    write_record(tmp_path / "decisions", "D-0002", "proposed")
    client = make_client(tmp_path)
    body = client.get("/api/records").json()
    ids = {r["id"] for r in body["records"]}
    assert ids == {"D-0001", "D-0002"}


def test_candidates_returns_only_proposed(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "accepted")
    write_record(tmp_path / "decisions", "D-0002", "proposed")
    write_record(tmp_path / "lessons", "L-0001", "proposed")
    client = make_client(tmp_path)
    body = client.get("/api/candidates").json()
    ids = {r["id"] for r in body["candidates"]}
    assert ids == {"D-0002", "L-0001"}


def test_records_filter_by_type(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "accepted")
    write_record(tmp_path / "lessons", "L-0001", "accepted")
    client = make_client(tmp_path)
    body = client.get("/api/records", params={"type": "lesson"}).json()
    ids = {r["id"] for r in body["records"]}
    assert ids == {"L-0001"}
