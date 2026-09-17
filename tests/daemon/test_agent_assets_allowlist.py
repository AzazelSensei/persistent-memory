import pytest

from persistent_memory.daemon.agent_assets import (
    AssetRoots,
    build_inventory,
    is_safe_segment,
    resolve_asset_path,
)


@pytest.fixture
def roots(tmp_path):
    claude = tmp_path / "claude"
    (claude / "projects" / "proj-a" / "memory").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("kurallar", encoding="utf-8")
    (claude / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    (claude / "settings.local.json").write_text('{"gizli": true}', encoding="utf-8")
    (claude / "projects" / "proj-a" / "memory" / "not.md").write_text("not", encoding="utf-8")

    codex = tmp_path / "codex"
    (codex / "memories").mkdir(parents=True)
    (codex / "rules").mkdir(parents=True)
    (codex / "AGENTS.md").write_text("codex kuralları", encoding="utf-8")
    (codex / "auth.json").write_text('{"OPENAI_API_KEY": "sk-gizli"}', encoding="utf-8")
    (codex / "config.toml").write_text('model = "gpt"', encoding="utf-8")
    (codex / "memories" / "auth.json").write_text('{"token": "gizli"}', encoding="utf-8")

    grok = tmp_path / "grok"
    grok.mkdir()
    (grok / "auth.json").write_text('{"XAI_API_KEY": "xai-gizli"}', encoding="utf-8")

    return AssetRoots(
        claude_root=claude,
        projects_root=claude / "projects",
        codex_root=codex,
        grok_root=grok,
    )


@pytest.mark.parametrize(
    "asset_id",
    [
        "codex:rules:global:auth.json",
        "codex:rules:global:config.toml",
        "codex:memory:global:auth.json",
        "grok:rules:global:auth.json",
        "claude:rules:global:settings.json",
        "claude:rules:global:settings.local.json",
        "claude:memory:proj-a:settings.json",
        "claude:settings:global:CLAUDE.md",
        "claude:rules:global:AGENTS.md",
    ],
)
def test_credential_and_cross_layer_ids_are_rejected(asset_id, roots):
    with pytest.raises((ValueError, FileNotFoundError)):
        resolve_asset_path(asset_id, roots)


def test_non_global_scope_rejected_for_fixed_layers(roots):
    with pytest.raises(ValueError):
        resolve_asset_path("claude:rules:baska:CLAUDE.md", roots)


def test_unknown_memory_file_is_not_resolvable(roots):
    with pytest.raises(FileNotFoundError):
        resolve_asset_path("claude:memory:proj-a:yok.md", roots)


def test_every_inventory_asset_resolves(roots):
    for asset in build_inventory(roots)["assets"]:
        assert resolve_asset_path(asset["id"], roots).is_file()


def test_credential_files_are_absent_from_inventory(roots):
    names = {a["name"] for a in build_inventory(roots)["assets"]}
    assert "auth.json" not in names
    assert "config.toml" not in names


def test_settings_layer_is_read_only(roots):
    assert resolve_asset_path("claude:settings:global:settings.json", roots).is_file()
    with pytest.raises(ValueError):
        resolve_asset_path("claude:settings:global:settings.json", roots, for_write=True)
    with pytest.raises(ValueError):
        resolve_asset_path("claude:settings:global:settings.local.json", roots, for_write=True)


def test_rules_and_memory_layers_stay_writable(roots):
    assert resolve_asset_path("claude:rules:global:CLAUDE.md", roots, for_write=True).is_file()
    assert resolve_asset_path("claude:memory:proj-a:not.md", roots, for_write=True).is_file()


@pytest.mark.parametrize(
    "segment",
    ["CLAUDE.md\n", "CLAUDE.md\n.env", "..", ".", "", "a/b", "a\\b", "a\x00b"],
)
def test_unsafe_segments_rejected(segment):
    assert is_safe_segment(segment) is False


@pytest.mark.parametrize("segment", ["CLAUDE.md", "ipuçları.md", "İŞ-notları.md", "proj_a"])
def test_unicode_segments_accepted(segment):
    assert is_safe_segment(segment) is True


def test_trailing_newline_segment_rejected_by_resolver(roots):
    with pytest.raises(ValueError):
        resolve_asset_path("claude:rules:global:CLAUDE.md\n", roots)


def test_turkish_memory_file_is_listed_and_resolvable(roots):
    memory_dir = roots.projects_root / "proj-a" / "memory"
    (memory_dir / "ipuçları.md").write_text("öğrenilenler", encoding="utf-8")

    ids = [a["id"] for a in build_inventory(roots)["assets"]]
    assert "claude:memory:proj-a:ipuçları.md" in ids

    path = resolve_asset_path("claude:memory:proj-a:ipuçları.md", roots)
    assert path.read_text(encoding="utf-8") == "öğrenilenler"


def test_turkish_project_scope_is_listed(roots):
    memory_dir = roots.projects_root / "şirket-projesi" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("içerik", encoding="utf-8")

    ids = [a["id"] for a in build_inventory(roots)["assets"]]
    assert "claude:memory:şirket-projesi:MEMORY.md" in ids
