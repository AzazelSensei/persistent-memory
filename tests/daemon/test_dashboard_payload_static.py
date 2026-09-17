import json
import re

from starlette.testclient import TestClient

from persistent_memory.daemon.app import STATIC_DIR, TEMPLATES_DIR, create_app
from persistent_memory.daemon.config import DaemonConfig

PM_STATIC = STATIC_DIR / "pm"


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _parse_pm(body: str) -> dict:
    start = body.index("window.PM = ") + len("window.PM = ")
    end = body.index(";\n", start)
    return json.loads(body[start:end])


def test_template_derives_byid_from_all():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "window.PM.byId = Object.fromEntries(window.PM.all.map(" in html


def test_template_derives_decisions_and_lessons_from_all():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert 'window.PM.decisions = window.PM.all.filter(' in html
    assert 'window.PM.lessons = window.PM.all.filter(' in html
    assert 'r.kind === "decision"' in html
    assert 'r.kind === "lesson"' in html


def test_derivation_runs_before_react_loads():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    derive_pos = html.index("window.PM.byId = Object.fromEntries")
    react_pos = html.index("react@18")
    assert derive_pos < react_pos


def test_template_wires_fetch_record_sections_helper():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "fetchRecordSections: function (id)" in html
    assert '"/api/records/" + encodeURIComponent(id) + "/sections"' in html


def test_get_root_html_contains_derivation_code(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "window.PM.byId = Object.fromEntries" in resp.text
    assert "window.PM.decisions = window.PM.all.filter(" in resp.text
    assert "window.PM.lessons = window.PM.all.filter(" in resp.text


def test_get_root_payload_has_no_byid_decisions_lessons_keys(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    pm = _parse_pm(resp.text)
    assert "byId" not in pm
    assert "decisions" not in pm
    assert "lessons" not in pm
    assert "all" in pm


def test_get_root_payload_records_have_no_sections_field(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    pm = _parse_pm(resp.text)
    for record in pm["all"]:
        assert "sections" not in record


def test_views_detail_fetches_sections_lazily_not_from_payload():
    detail_jsx = (PM_STATIC / "views-detail.jsx").read_text(encoding="utf-8")
    assert "fetchRecordSections" in detail_jsx
    assert "rec.sections" not in detail_jsx


def test_views_detail_has_sections_loading_and_error_states():
    detail_jsx = (PM_STATIC / "views-detail.jsx").read_text(encoding="utf-8")
    assert "sectionsErr" in detail_jsx
    assert "ui.detail.sections_error" in detail_jsx
    assert "ui.detail.sections_loading" in detail_jsx


def test_views_list_queue_fetches_sections_lazily_not_from_payload():
    list_jsx = (PM_STATIC / "views-list.jsx").read_text(encoding="utf-8")
    assert "fetchRecordSections" in list_jsx
    assert "rec.sections" not in list_jsx


def test_views_misc_search_no_longer_reads_sections():
    misc_jsx = (PM_STATIC / "views-misc.jsx").read_text(encoding="utf-8")
    assert ".sections" not in misc_jsx


def test_shared_helper_pmbyid_guards_prototype_pollution():
    components_jsx = (PM_STATIC / "components.jsx").read_text(encoding="utf-8")
    assert "function pmById(id)" in components_jsx
    assert "hasOwnProperty" in components_jsx
    assert "pmById" in components_jsx


def test_no_jsx_indexes_pm_byid_without_the_guarded_helper():
    for path in PM_STATIC.glob("*.jsx"):
        if path.name == "components.jsx":
            continue
        text = path.read_text(encoding="utf-8")
        assert "PM.byId[" not in text, f"{path.name} indexes PM.byId directly; route it through pmById()"


def test_views_that_reference_byid_import_pmbyid_helper():
    for name in ("app.jsx", "views-candidates.jsx", "views-detail.jsx", "views-graph.jsx"):
        text = (PM_STATIC / name).read_text(encoding="utf-8")
        assert "pmById" in text, f"{name} should use the shared pmById() helper"


def test_council_view_still_guards_its_own_registry_lookup():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "hasOwnProperty" in council_jsx
    assert re.search(r"registry\[id\]", council_jsx)
