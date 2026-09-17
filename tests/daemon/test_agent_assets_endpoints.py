from pathlib import Path

import pytest
from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token


@pytest.fixture
def records_dir(tmp_path):
    records = tmp_path / "records"
    (records / "decisions").mkdir(parents=True)
    (records / "lessons").mkdir(parents=True)
    return records


@pytest.fixture
def asset_roots(tmp_path, monkeypatch):
    from persistent_memory.daemon import agent_assets

    claude = tmp_path / "claude"
    (claude / "projects" / "proj-a" / "memory").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("global kurallar", encoding="utf-8")
    (claude / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    (claude / "projects" / "proj-a" / "memory" / "not.md").write_text("bir not", encoding="utf-8")

    codex = tmp_path / "codex"
    (codex / "rules").mkdir(parents=True)
    (codex / "auth.json").write_text('{"OPENAI_API_KEY": "sk-gizli"}', encoding="utf-8")
    (codex / "config.toml").write_text('model = "gpt"', encoding="utf-8")

    roots = agent_assets.AssetRoots(
        claude_root=claude,
        projects_root=claude / "projects",
        codex_root=codex,
        grok_root=tmp_path / "grok",
    )
    monkeypatch.setattr(agent_assets, "default_roots", lambda: roots)
    return roots


@pytest.fixture
def client(records_dir, asset_roots):
    cfg = DaemonConfig(records_dir=records_dir, watch_enabled=False)
    return TestClient(create_app(records_dir=records_dir, config=cfg))


@pytest.fixture
def headers(records_dir):
    return {"X-PM-Token": load_or_create_token(records_dir)}


def test_inventory_endpoint_lists_assets(client, headers):
    response = client.get("/api/agent-assets", headers=headers)
    assert response.status_code == 200
    ids = [a["id"] for a in response.json()["assets"]]
    assert "claude:memory:proj-a:not.md" in ids


def test_raw_endpoint_returns_content(client, headers):
    response = client.get("/api/agent-assets/claude:memory:proj-a:not.md/raw", headers=headers)
    assert response.status_code == 200
    assert response.json()["content"] == "bir not"


def test_raw_endpoint_rejects_traversal(client, headers):
    response = client.get("/api/agent-assets/claude:memory:..:not.md/raw", headers=headers)
    assert response.status_code == 400


def test_raw_endpoint_missing_file_is_404(client, headers):
    response = client.get("/api/agent-assets/claude:memory:proj-a:yok.md/raw", headers=headers)
    assert response.status_code == 404


def test_inventory_endpoint_requires_token(client):
    assert client.get("/api/agent-assets").status_code == 403


def test_raw_endpoint_requires_token(client):
    response = client.get("/api/agent-assets/claude:memory:proj-a:not.md/raw")
    assert response.status_code == 403


def test_raw_endpoint_requires_token_for_credential_file(client):
    response = client.get("/api/agent-assets/codex:rules:global:auth.json/raw")
    assert response.status_code == 403


@pytest.mark.parametrize(
    "asset_id",
    [
        "codex:rules:global:auth.json",
        "codex:rules:global:config.toml",
        "codex:memory:global:auth.json",
        "claude:rules:global:settings.json",
        "claude:rules:global:settings.local.json",
        "grok:rules:global:auth.json",
    ],
)
def test_raw_endpoint_never_serves_credential_files(client, headers, asset_id):
    response = client.get(f"/api/agent-assets/{asset_id}/raw", headers=headers)
    assert response.status_code in (400, 404)
    assert "sk-gizli" not in response.text


def test_credential_files_never_appear_in_inventory(client, headers):
    ids = [a["id"] for a in client.get("/api/agent-assets", headers=headers).json()["assets"]]
    assert not any(name in i for i in ids for name in ("auth.json", "config.toml"))


def test_save_endpoint_refuses_settings_file(client, headers, asset_roots):
    response = client.post(
        "/api/agent-assets/claude:settings:global:settings.json",
        json={"content": '{"hooks": {"PreToolUse": "rm -rf /"}}'},
        headers=headers,
    )
    assert response.status_code == 400
    assert (asset_roots.claude_root / "settings.json").read_text(encoding="utf-8") == '{"hooks": {}}'


def test_save_endpoint_refuses_credential_file(client, headers, asset_roots):
    response = client.post(
        "/api/agent-assets/codex:rules:global:auth.json",
        json={"content": "ele geçirildi"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "sk-gizli" in (asset_roots.codex_root / "auth.json").read_text(encoding="utf-8")


def test_save_backup_lands_outside_the_repository(client, headers, asset_roots):
    response = client.post(
        "/api/agent-assets/claude:memory:proj-a:not.md",
        json={"content": "değişti"},
        headers=headers,
    )
    backup = Path(response.json()["backup"])
    repo_root = Path(__file__).resolve().parents[2]
    assert not backup.is_relative_to(repo_root)
    assert backup.is_relative_to(asset_roots.claude_root / "backups" / "agent-assets")


def test_save_requires_token(client):
    response = client.post(
        "/api/agent-assets/claude:memory:proj-a:not.md",
        json={"content": "değişti"},
    )
    assert response.status_code == 403


def test_save_with_token_writes_content(client, headers):
    response = client.post(
        "/api/agent-assets/claude:memory:proj-a:not.md",
        json={"content": "değişti"},
        headers=headers,
    )
    assert response.status_code == 200
    raw = client.get("/api/agent-assets/claude:memory:proj-a:not.md/raw", headers=headers)
    assert raw.json()["content"] == "değişti"
