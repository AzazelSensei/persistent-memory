import pytest

from persistent_memory.daemon.agent_assets import AssetRoots, resolve_asset_path


@pytest.fixture
def roots(tmp_path):
    return AssetRoots(
        claude_root=tmp_path / "claude",
        projects_root=tmp_path / "claude" / "projects",
        codex_root=tmp_path / "codex",
        grok_root=tmp_path / "grok",
    )


def test_resolves_claude_global_rules(roots):
    path = resolve_asset_path("claude:rules:global:CLAUDE.md", roots)
    assert path == roots.claude_root / "CLAUDE.md"


def test_resolves_project_memory(roots):
    memory_dir = roots.projects_root / "my-project" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "notes.md").write_text("not", encoding="utf-8")
    path = resolve_asset_path("claude:memory:my-project:notes.md", roots)
    assert path == memory_dir / "notes.md"


def test_resolves_codex_rules_file(roots):
    path = resolve_asset_path("codex:rules:global:default.rules", roots)
    assert path == roots.codex_root / "rules" / "default.rules"


@pytest.mark.parametrize(
    "asset_id",
    [
        "claude:memory:my-project:../../../etc/passwd",
        "claude:memory:..:notes.md",
        "claude:memory::notes.md",
        "claude:memory:my-project:sub/dir.md",
        "claude:rules:global:secrets.env",
        "unknown:rules:global:CLAUDE.md",
        "claude:unknown:global:CLAUDE.md",
        "claude:rules:global",
    ],
)
def test_rejects_malformed_or_unsafe_ids(asset_id, roots):
    with pytest.raises(ValueError):
        resolve_asset_path(asset_id, roots)


def test_rejects_symlink_escaping_root(roots, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("gizli", encoding="utf-8")
    memory_dir = roots.projects_root / "p" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "link.md").symlink_to(outside / "secret.md")

    with pytest.raises(ValueError):
        resolve_asset_path("claude:memory:p:link.md", roots)
