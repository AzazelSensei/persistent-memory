import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _headers(tmp_path):
    return {"X-PM-Token": load_or_create_token(tmp_path)}


def write_record(records_dir, rec_id, status="accepted"):
    directory = records_dir / "decisions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec_id}.md").write_text(
        textwrap.dedent(f"""\
            ---
            id: {rec_id}
            type: decision
            status: {status}
            date: '2026-06-02'
            project: alpha
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


def test_link_endpoint_links_records(tmp_path):
    write_record(tmp_path, "D-0001")
    write_record(tmp_path, "D-0002")
    client = _client(tmp_path)
    resp = client.post(
        "/api/records/D-0001/supersede-by/D-0002", headers=_headers(tmp_path)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["old"] == {"id": "D-0001", "status": "superseded", "superseded_by": ["D-0002"]}
    assert body["new"] == {"id": "D-0002", "status": "accepted", "supersedes": ["D-0001"]}
    assert body["already_linked"] is False


def test_link_endpoint_idempotent_repeat(tmp_path):
    write_record(tmp_path, "D-0001")
    write_record(tmp_path, "D-0002")
    client = _client(tmp_path)
    client.post("/api/records/D-0001/supersede-by/D-0002", headers=_headers(tmp_path))
    resp = client.post(
        "/api/records/D-0001/supersede-by/D-0002", headers=_headers(tmp_path)
    )
    assert resp.status_code == 200
    assert resp.json()["already_linked"] is True


def test_link_endpoint_conflict_returns_409(tmp_path):
    write_record(tmp_path, "D-0001")
    client = _client(tmp_path)
    resp = client.post(
        "/api/records/D-0001/supersede-by/D-0001", headers=_headers(tmp_path)
    )
    assert resp.status_code == 409
    assert "cannot supersede itself" in resp.json()["detail"]


def test_link_endpoint_unknown_record_returns_404(tmp_path):
    write_record(tmp_path, "D-0001")
    client = _client(tmp_path)
    resp = client.post(
        "/api/records/D-0001/supersede-by/D-9999", headers=_headers(tmp_path)
    )
    assert resp.status_code == 404


def test_link_endpoint_malformed_id_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/records/D-1/supersede-by/D-0002", headers=_headers(tmp_path)
    )
    assert resp.status_code == 422


def test_link_endpoint_without_token_returns_403(tmp_path):
    write_record(tmp_path, "D-0001")
    write_record(tmp_path, "D-0002")
    client = _client(tmp_path)
    resp = client.post("/api/records/D-0001/supersede-by/D-0002")
    assert resp.status_code == 403
