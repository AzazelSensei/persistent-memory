from starlette.testclient import TestClient

from persistent_memory.daemon.app import STATIC_DIR, TEMPLATES_DIR, create_app
from persistent_memory.daemon.config import DaemonConfig

PM_STATIC = STATIC_DIR / "pm"


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def test_app_page_loads_candidates_view(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "views-candidates.jsx" in resp.text
    assert "fetchSupersessionCandidates" in resp.text
    assert "linkSupersession" in resp.text
    assert "dismissCandidate" in resp.text


def test_candidates_static_file_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/pm/views-candidates.jsx")
    assert resp.status_code == 200
    assert "PMCandidates" in resp.text


def test_nav_registers_supersession_view():
    app_jsx = (PM_STATIC / "app.jsx").read_text(encoding="utf-8")
    assert '"supersession"' in app_jsx
    assert "PMCandidates" in app_jsx


def test_dashboard_panel_has_candidate_counter():
    dashboard_jsx = (PM_STATIC / "views-dashboard.jsx").read_text(encoding="utf-8")
    assert "Supersession candidates" in dashboard_jsx
    assert "fetchSupersessionCandidates" in dashboard_jsx


def test_template_wires_candidates_script():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "/static/pm/views-candidates.jsx" in html
    assert "/api/supersession-candidates" in html
