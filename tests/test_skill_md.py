from pathlib import Path

import frontmatter

SKILL_PATH = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"


def test_skill_file_exists():
    assert SKILL_PATH.exists()


def test_frontmatter_has_required_fields():
    post = frontmatter.load(SKILL_PATH)
    assert post["name"] == "persistent-memory"
    assert isinstance(post["description"], str) and len(post["description"]) > 20


def test_documents_manual_commands():
    body = SKILL_PATH.read_text(encoding="utf-8")
    for command in ("/decision", "/lesson", "/recall", "/consolidate"):
        assert command in body


def test_mentions_automatic_and_local():
    body = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert "automatic" in body
    assert "local" in body or "no extra api key" in body


def test_documents_host_agnostic_access():
    body = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert "codex" in body
    assert "mcp" in body
    assert "search_memory" in body
    assert "/api/search" in body
    assert "x-pm-token" in body


def test_writing_records_section_exists():
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "Writing records" in body


def test_writing_records_documents_http_endpoint():
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "/api/records" in body
    assert "POST" in body


def test_writing_records_documents_direct_file_write():
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "Direct file write" in body or "direct file write" in body.lower()
    assert "## Context / Problem" in body
    assert "## What happened" in body


def test_writing_records_documents_automatic_extraction():
    body = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert "automatic extraction" in body or ("automatic" in body and "extraction" in body)


def test_notes_no_longer_points_to_mcp_calls_only():
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "their equivalents are the MCP/HTTP calls above" not in body


def test_writing_records_documents_token_location():
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "daemon.token" in body
