"""GET /api/records/{id}/sections: lazy per-record section fetch for the
detail view, now that the bulk payload no longer embeds section bodies."""

import textwrap

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app


def _write_record(directory, rec_id, rec_type):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec_id}.md").write_text(
        textwrap.dedent(f"""\
            ---
            id: {rec_id}
            type: {rec_type}
            status: proposed
            date: '2026-06-11'
            project: alpha
            provenance:
              session: s-1
              cwd: /tmp/work
              agent: claude-sonnet-4-6
            tags: []
            supersedes: []
            superseded-by: []
            salience: 0.5
            ---
            # Title for {rec_id}

            ## Context
            some context text

            ## Decision
            some decision text
            """),
        encoding="utf-8",
    )


def test_sections_endpoint_returns_id_and_sections(tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision")
    client = TestClient(create_app(records_dir=tmp_path))

    resp = client.get("/api/records/D-0001/sections")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "D-0001"
    labels = [s["label"] for s in data["sections"]]
    assert "Context" in labels
    assert "Decision" in labels


def test_sections_endpoint_requires_no_token(tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision")
    client = TestClient(create_app(records_dir=tmp_path))

    resp = client.get("/api/records/D-0001/sections", headers={})

    assert resp.status_code == 200


def test_sections_endpoint_404_for_missing_record(tmp_path):
    client = TestClient(create_app(records_dir=tmp_path))

    resp = client.get("/api/records/D-9999/sections")

    assert resp.status_code == 404


def test_sections_endpoint_422_for_malformed_id(tmp_path):
    client = TestClient(create_app(records_dir=tmp_path))

    resp = client.get("/api/records/not-an-id/sections")

    assert resp.status_code == 422
