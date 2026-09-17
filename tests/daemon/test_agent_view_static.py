from pathlib import Path

STATIC_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "persistent_memory" / "daemon" / "static" / "pm"
)


def test_agents_view_exports_component():
    source = (STATIC_DIR / "views-agents.jsx").read_text(encoding="utf-8")
    assert "window.PMAgents" in source


def test_app_shell_loads_agents_view():
    template = (
        Path(__file__).resolve().parents[2]
        / "src" / "persistent_memory" / "daemon" / "templates" / "app.html"
    ).read_text(encoding="utf-8")
    assert "views-agents.jsx" in template
    assert template.index("views-agents.jsx") < template.index("app.jsx?v=")


def test_app_routes_agents_view():
    source = (STATIC_DIR / "app.jsx").read_text(encoding="utf-8")
    assert 'view === "agents"' in source
    assert "window.PMAgents" in source
    assert '"ui.nav.agents"' in source


def test_api_client_exposes_agent_asset_calls():
    template = (
        Path(__file__).resolve().parents[2]
        / "src" / "persistent_memory" / "daemon" / "templates" / "app.html"
    ).read_text(encoding="utf-8")
    for fn in ("fetchAgentAssets", "fetchAgentAssetRaw", "saveAgentAsset"):
        assert fn in template
