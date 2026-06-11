import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _token(tmp_path):
    return load_or_create_token(tmp_path)


def write_record(directory, rec_id, rec_type, status, project="alpha"):
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
            # Baslik {rec_id}

            ## Karar
            govde
            """),
        encoding="utf-8",
    )


def _status(directory, rec_id):
    from persistent_memory.records import read_record
    record, _ = read_record(directory / f"{rec_id}.md")
    return record.status.value


def test_accept_all_requires_token(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed")
    client = _client(tmp_path)
    resp = client.post("/api/records/accept-all")
    assert resp.status_code == 403


def test_accept_all_flips_proposed_with_token(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed")
    write_record(tmp_path / "lessons", "L-0001", "lesson", "proposed")
    client = _client(tmp_path)
    resp = client.post("/api/records/accept-all", headers={"X-PM-Token": _token(tmp_path)})
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 2
    assert _status(tmp_path / "decisions", "D-0001") == "accepted"
    assert _status(tmp_path / "lessons", "L-0001") == "accepted"


def test_accept_all_respects_type_filter(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed")
    write_record(tmp_path / "lessons", "L-0001", "lesson", "proposed")
    client = _client(tmp_path)
    resp = client.post(
        "/api/records/accept-all",
        params={"type": "decision"},
        headers={"X-PM-Token": _token(tmp_path)},
    )
    assert resp.json()["accepted"] == 1
    assert _status(tmp_path / "decisions", "D-0001") == "accepted"
    assert _status(tmp_path / "lessons", "L-0001") == "proposed"
