import pytest

from persistent_memory.daemon.agent_assets import AssetRoots, build_inventory


@pytest.fixture
def roots(tmp_path):
    claude = tmp_path / "claude"
    (claude / "projects" / "proj-a" / "memory").mkdir(parents=True)
    (claude / "projects" / "proj-b" / "memory").mkdir(parents=True)
    (claude / "projects" / "bos-proje" / "memory").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("global kurallar", encoding="utf-8")
    (claude / "projects" / "proj-a" / "memory" / "MEMORY.md").write_text("index", encoding="utf-8")
    (claude / "projects" / "proj-a" / "memory" / "not.md").write_text("bir not", encoding="utf-8")
    (claude / "projects" / "proj-b" / "memory" / "MEMORY.md").write_text("index", encoding="utf-8")

    codex = tmp_path / "codex"
    (codex / "memories").mkdir(parents=True)
    (codex / "AGENTS.md").write_text("codex kuralları", encoding="utf-8")
    (codex / "memories" / "MEMORY.md").write_text("codex hafıza", encoding="utf-8")

    return AssetRoots(
        claude_root=claude,
        projects_root=claude / "projects",
        codex_root=codex,
        grok_root=tmp_path / "grok",
    )


def test_lists_claude_global_rules(roots):
    inventory = build_inventory(roots)
    ids = [a["id"] for a in inventory["assets"]]
    assert "claude:rules:global:CLAUDE.md" in ids


def test_lists_project_memory_files(roots):
    inventory = build_inventory(roots)
    ids = [a["id"] for a in inventory["assets"]]
    assert "claude:memory:proj-a:not.md" in ids
    assert "claude:memory:proj-b:MEMORY.md" in ids


def test_skips_projects_without_memory_files(roots):
    inventory = build_inventory(roots)
    projects = {g["scope"] for g in inventory["groups"] if g["layer"] == "memory"}
    assert "bos-proje" not in projects


def test_reports_size_and_mtime(roots):
    inventory = build_inventory(roots)
    asset = next(a for a in inventory["assets"] if a["id"] == "claude:memory:proj-a:not.md")
    assert asset["size"] == len("bir not")
    assert asset["mtime"]


def test_missing_root_is_skipped_not_fatal(roots):
    inventory = build_inventory(roots)
    assert not any(a["agent"] == "grok" for a in inventory["assets"])


def test_group_counts_match_assets(roots):
    inventory = build_inventory(roots)
    group = next(
        g for g in inventory["groups"] if g["layer"] == "memory" and g["scope"] == "proj-a"
    )
    assert group["count"] == 2
