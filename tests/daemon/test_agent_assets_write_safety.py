import os
import stat
from pathlib import Path

import pytest

from persistent_memory.daemon.agent_assets import (
    BACKUP_ROOT,
    AssetRoots,
    build_inventory,
    default_backup_root,
    write_asset,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def roots(tmp_path):
    claude = tmp_path / "claude"
    (claude / "projects" / "proj-a" / "memory").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("ilk içerik", encoding="utf-8")
    (claude / "projects" / "proj-a" / "memory" / "not.md").write_text("not", encoding="utf-8")
    return AssetRoots(
        claude_root=claude,
        projects_root=claude / "projects",
        codex_root=tmp_path / "codex",
        grok_root=tmp_path / "grok",
    )


def test_backup_root_is_outside_the_repository():
    assert not BACKUP_ROOT.is_relative_to(REPO_ROOT)
    assert BACKUP_ROOT == Path.home() / ".claude" / "backups" / "agent-assets"


def test_default_backup_root_follows_the_claude_root(roots):
    assert default_backup_root(roots) == roots.claude_root / "backups" / "agent-assets"


def test_write_without_explicit_backup_root_stays_outside_the_repository(roots):
    result = write_asset("claude:rules:global:CLAUDE.md", "yeni", roots)
    backup = Path(result["backup"])
    assert backup.is_relative_to(default_backup_root(roots))
    assert not backup.is_relative_to(REPO_ROOT)
    assert backup.read_text(encoding="utf-8") == "ilk içerik"


def test_backup_directory_is_private(roots):
    write_asset("claude:rules:global:CLAUDE.md", "yeni", roots)
    mode = stat.S_IMODE(default_backup_root(roots).stat().st_mode)
    assert mode == 0o700


def test_write_preserves_restrictive_permissions(roots):
    target = roots.claude_root / "CLAUDE.md"
    os.chmod(target, 0o600)
    write_asset("claude:rules:global:CLAUDE.md", "yeni içerik", roots)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_write_preserves_group_readable_permissions(roots):
    target = roots.claude_root / "CLAUDE.md"
    os.chmod(target, 0o640)
    write_asset("claude:rules:global:CLAUDE.md", "yeni içerik", roots)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_write_follows_symlink_and_keeps_it(roots, tmp_path):
    real_target = roots.claude_root / "projects" / "proj-a" / "memory" / "gercek.md"
    real_target.write_text("eski", encoding="utf-8")
    link = roots.claude_root / "projects" / "proj-a" / "memory" / "link.md"
    link.symlink_to(real_target)

    write_asset("claude:memory:proj-a:link.md", "yeni içerik", roots)

    assert link.is_symlink()
    assert real_target.read_text(encoding="utf-8") == "yeni içerik"
    assert link.readlink() == real_target


def test_write_through_symlink_preserves_target_permissions(roots):
    real_target = roots.claude_root / "projects" / "proj-a" / "memory" / "gercek.md"
    real_target.write_text("eski", encoding="utf-8")
    os.chmod(real_target, 0o600)
    link = roots.claude_root / "projects" / "proj-a" / "memory" / "link.md"
    link.symlink_to(real_target)

    write_asset("claude:memory:proj-a:link.md", "yeni", roots)

    assert stat.S_IMODE(real_target.stat().st_mode) == 0o600


def test_write_rejects_symlink_escaping_root(roots, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("gizli", encoding="utf-8")
    link = roots.claude_root / "projects" / "proj-a" / "memory" / "kacak.md"
    link.symlink_to(secret)

    with pytest.raises(ValueError):
        write_asset("claude:memory:proj-a:kacak.md", "ele geçirildi", roots)
    assert secret.read_text(encoding="utf-8") == "gizli"


def test_write_rejects_symlink_crossing_into_another_layer(roots):
    settings = roots.claude_root / "settings.json"
    settings.write_text('{"orijinal": true}', encoding="utf-8")
    link = roots.claude_root / "projects" / "proj-a" / "memory" / "capraz.md"
    link.symlink_to(settings)

    with pytest.raises(ValueError):
        write_asset("claude:memory:proj-a:capraz.md", "ELE GEÇİRİLDİ", roots)
    assert settings.read_text(encoding="utf-8") == '{"orijinal": true}'


def test_inventory_skips_symlink_crossing_into_another_layer(roots):
    settings = roots.claude_root / "settings.json"
    settings.write_text('{"orijinal": true}', encoding="utf-8")
    link = roots.claude_root / "projects" / "proj-a" / "memory" / "capraz.md"
    link.symlink_to(settings)

    ids = [asset["id"] for asset in build_inventory(roots)["assets"]]
    assert "claude:memory:proj-a:capraz.md" not in ids


def test_write_refuses_read_only_settings_layer(roots):
    settings = roots.claude_root / "settings.json"
    settings.write_text('{"hooks": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        write_asset("claude:settings:global:settings.json", '{"hooks": {"x": "kabuk"}}', roots)
    assert settings.read_text(encoding="utf-8") == '{"hooks": {}}'


def test_two_writes_in_the_same_second_keep_both_backups(roots):
    first = write_asset("claude:rules:global:CLAUDE.md", "ikinci", roots)
    second = write_asset("claude:rules:global:CLAUDE.md", "üçüncü", roots)

    assert first["backup"] != second["backup"]
    assert Path(first["backup"]).read_text(encoding="utf-8") == "ilk içerik"
    assert Path(second["backup"]).read_text(encoding="utf-8") == "ikinci"
