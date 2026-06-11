from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app


def make_client(tmp_path):
    app = create_app(records_dir=tmp_path)
    return TestClient(app)


def test_health_returns_ok(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["host"] == "127.0.0.1"
    assert body["port"] == 37778


def test_health_reports_counts(tmp_path):
    (tmp_path / "decisions").mkdir()
    (tmp_path / "lessons").mkdir()
    client = make_client(tmp_path)
    body = client.get("/api/health").json()
    assert "decisions_count" in body
    assert "lessons_count" in body
    assert body["decisions_count"] == 0


def test_health_exposes_records_dir(tmp_path):
    from persistent_memory.daemon.app import create_app
    from persistent_memory.daemon.config import DaemonConfig
    from starlette.testclient import TestClient

    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    client = TestClient(create_app(records_dir=tmp_path, config=cfg))
    body = client.get("/api/health").json()
    assert body["records_dir"] == str(tmp_path)
