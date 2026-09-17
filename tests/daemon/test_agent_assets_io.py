from pathlib import Path

import pytest

from persistent_memory.daemon.agent_assets import (
    AssetRoots,
    read_asset,
    write_asset,
)


@pytest.fixture
def roots(tmp_path):
    claude = tmp_path / "claude"
    claude.mkdir()
    (claude / "CLAUDE.md").write_text("ilk içerik", encoding="utf-8")
    return AssetRoots(
        claude_root=claude,
        projects_root=claude / "projects",
        codex_root=tmp_path / "codex",
        grok_root=tmp_path / "grok",
    )


def test_reads_asset_content(roots):
    assert read_asset("claude:rules:global:CLAUDE.md", roots) == "ilk içerik"


def test_read_missing_asset_raises(roots):
    with pytest.raises(FileNotFoundError):
        read_asset("codex:rules:global:AGENTS.md", roots)


def test_write_replaces_content(roots, tmp_path):
    write_asset("claude:rules:global:CLAUDE.md", "yeni içerik", roots, tmp_path / "backups")
    assert (roots.claude_root / "CLAUDE.md").read_text(encoding="utf-8") == "yeni içerik"


def test_write_keeps_backup_of_previous_content(roots, tmp_path):
    backup_dir = tmp_path / "backups"
    result = write_asset("claude:rules:global:CLAUDE.md", "yeni içerik", roots, backup_dir)
    backup = Path(result["backup"])
    assert backup.read_text(encoding="utf-8") == "ilk içerik"


def test_write_leaves_no_temp_file_behind(roots, tmp_path):
    write_asset("claude:rules:global:CLAUDE.md", "yeni içerik", roots, tmp_path / "backups")
    leftovers = [p.name for p in roots.claude_root.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_write_rejects_unknown_asset(roots, tmp_path):
    with pytest.raises(ValueError):
        write_asset("claude:memory:..:x.md", "içerik", roots, tmp_path / "backups")
