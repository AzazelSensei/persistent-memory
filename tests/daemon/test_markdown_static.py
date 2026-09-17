"""Source-level invariants and wiring for the markdown renderer.

Behaviour is covered by ``test_markdown_behavior.py``, which runs the module in
node. Only assertions that cannot be expressed as behaviour belong here: the
absence of raw-HTML escape hatches, and the wiring of the asset into the app.
"""

from starlette.testclient import TestClient

from persistent_memory.daemon.app import STATIC_DIR, TEMPLATES_DIR, create_app
from persistent_memory.daemon.config import DaemonConfig

PM_STATIC = STATIC_DIR / "pm"

RAW_HTML_ESCAPE_HATCHES = [
    "dangerouslySetInnerHTML",
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "createContextualFragment",
]


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _read_markdown_jsx():
    return (PM_STATIC / "markdown.jsx").read_text(encoding="utf-8")


def test_markdown_static_file_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/pm/markdown.jsx")
    assert resp.status_code == 200
    assert "PMMarkdown" in resp.text


def test_app_html_wires_markdown_script_with_version():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "/static/pm/markdown.jsx?v={{ pm_asset_version }}" in html


def test_markdown_module_has_no_raw_html_escape_hatch():
    md = _read_markdown_jsx()
    for hatch in RAW_HTML_ESCAPE_HATCHES:
        assert hatch not in md, hatch


def test_markdown_module_never_names_a_navigable_url_attribute():
    md = _read_markdown_jsx()
    assert "href" not in md
    assert "src:" not in md
    assert "window.open" not in md


def test_markdown_module_builds_react_elements_rather_than_html_strings():
    md = _read_markdown_jsx()
    assert "const h = React.createElement" in md
    assert "window.PMMarkdown = { renderMarkdown }" in md


def test_markdown_module_pulls_in_no_third_party_renderer():
    md = _read_markdown_jsx()
    assert "import " not in md
    assert "require(" not in md
    assert "<script" not in md


def test_markdown_module_defines_public_style_block_once():
    md = _read_markdown_jsx()
    assert 'id = "pm-markdown-css"' in md
    assert 'getElementById("pm-markdown-css")' in md


def test_council_view_renders_message_bodies_through_markdown():
    council = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "window.PMMarkdown" in council
    assert "renderMarkdown" in council
    assert "renderRefs(msg.body" not in council
    assert ".cn-body.md{white-space:normal}" in council
