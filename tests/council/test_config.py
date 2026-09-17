"""Tests for .pm-council.yaml loading and validation."""

import pytest
from pydantic import ValidationError

from persistent_memory.council.config import (
    CONFIG_FILENAME,
    DEFAULT_MEMBER_IDS,
    DEFAULT_ROUNDS,
    DEFAULT_TURN_TIMEOUT_SECONDS,
    MAX_CONFIG_BYTES,
    MAX_EFFORT_CHARS,
    MAX_MEMBERS,
    MAX_MODEL_CHARS,
    MAX_ROUNDS,
    MAX_TOTAL_TURN_CALLS,
    MAX_TURN_TIMEOUT_SECONDS,
    SUPPORTED_CONFIG_VERSION,
    CouncilConfig,
    CouncilConfigError,
    CouncilMember,
    council_config_path,
    default_council_config,
    load_council_config,
)
from persistent_memory.council.models import MAX_PROMPT_CHARS


def _write_yaml(project_root, text):
    council_config_path(project_root).write_text(text, encoding="utf-8")


def _valid_yaml():
    return """
version: 1
spokesperson: claude
rounds: 2
turn_timeout_seconds: 600
members:
  - {id: claude, backend: claude, role: "Architect"}
  - {id: codex, backend: codex, role: "Implementer"}
"""


def test_council_config_path_uses_fixed_filename(tmp_path):
    assert council_config_path(tmp_path) == tmp_path / CONFIG_FILENAME


def test_default_council_config_has_default_members_and_backends():
    config = default_council_config()

    assert config.version == SUPPORTED_CONFIG_VERSION
    assert config.rounds == DEFAULT_ROUNDS
    assert config.turn_timeout_seconds == DEFAULT_TURN_TIMEOUT_SECONDS
    assert [member.id for member in config.members] == list(DEFAULT_MEMBER_IDS)
    assert [member.backend for member in config.members] == list(DEFAULT_MEMBER_IDS)
    assert config.spokesperson == DEFAULT_MEMBER_IDS[0]


def test_load_council_config_missing_file_returns_default(tmp_path):
    config, source = load_council_config(tmp_path)

    assert source == "default"
    assert config.model_dump() == default_council_config().model_dump()


def test_load_council_config_reads_valid_file(tmp_path):
    _write_yaml(tmp_path, _valid_yaml())

    config, source = load_council_config(tmp_path)

    assert source == "file"
    assert config.rounds == 2
    assert config.spokesperson == "claude"
    assert [m.id for m in config.members] == ["claude", "codex"]


def test_load_council_config_broken_yaml_raises_council_config_error(tmp_path):
    _write_yaml(tmp_path, "version: [1, 2\nmembers: broken")

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_unknown_backend_raises(tmp_path):
    _write_yaml(
        tmp_path,
        """
version: 1
members:
  - {id: mystery, backend: not-a-real-backend}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_duplicate_member_ids_raises(tmp_path):
    _write_yaml(
        tmp_path,
        """
version: 1
members:
  - {id: claude, backend: claude}
  - {id: claude, backend: codex}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_spokesperson_not_in_members_raises(tmp_path):
    _write_yaml(
        tmp_path,
        """
version: 1
spokesperson: ghost
members:
  - {id: claude, backend: claude}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_spokesperson_disabled_member_raises(tmp_path):
    _write_yaml(
        tmp_path,
        """
version: 1
spokesperson: claude
members:
  - {id: claude, backend: claude, enabled: false}
  - {id: codex, backend: codex}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_disabled_member_preserved_when_not_spokesperson(tmp_path):
    _write_yaml(
        tmp_path,
        """
version: 1
spokesperson: codex
members:
  - {id: claude, backend: claude, enabled: false}
  - {id: codex, backend: codex}
""",
    )

    config, source = load_council_config(tmp_path)

    assert source == "file"
    claude_member = next(m for m in config.members if m.id == "claude")
    assert claude_member.enabled is False


def test_load_council_config_rounds_out_of_bounds_raises(tmp_path):
    _write_yaml(
        tmp_path,
        f"""
version: 1
rounds: {MAX_ROUNDS + 1}
members:
  - {{id: claude, backend: claude}}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_timeout_out_of_bounds_raises(tmp_path):
    _write_yaml(
        tmp_path,
        f"""
version: 1
turn_timeout_seconds: {MAX_TURN_TIMEOUT_SECONDS + 1}
members:
  - {{id: claude, backend: claude}}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_unsupported_version_raises(tmp_path):
    _write_yaml(
        tmp_path,
        """
version: 99
members:
  - {id: claude, backend: claude}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_no_members_raises(tmp_path):
    _write_yaml(tmp_path, "version: 1\nmembers: []\n")

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_unknown_field_raises(tmp_path):
    _write_yaml(
        tmp_path,
        """
version: 1
members:
  - {id: claude, backend: claude}
mystery_field: true
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


# ---------------------------------------------------------------------------
# Cost cap: MAX_MEMBERS / MAX_TOTAL_TURN_CALLS
# ---------------------------------------------------------------------------

def _members_yaml_block(count):
    lines = [f"  - {{id: m{i}, backend: claude}}" for i in range(count)]
    return "\n".join(lines)


def test_load_council_config_too_many_members_raises(tmp_path):
    _write_yaml(
        tmp_path,
        f"""
version: 1
members:
{_members_yaml_block(MAX_MEMBERS + 1)}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_max_members_at_max_rounds_exceeds_call_cap(tmp_path):
    assert MAX_MEMBERS * MAX_ROUNDS + 1 > MAX_TOTAL_TURN_CALLS
    _write_yaml(
        tmp_path,
        f"""
version: 1
rounds: {MAX_ROUNDS}
members:
{_members_yaml_block(MAX_MEMBERS)}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_within_call_cap_passes(tmp_path):
    assert 4 * MAX_ROUNDS + 1 <= MAX_TOTAL_TURN_CALLS
    _write_yaml(
        tmp_path,
        f"""
version: 1
rounds: {MAX_ROUNDS}
members:
{_members_yaml_block(4)}
""",
    )

    config, source = load_council_config(tmp_path)

    assert source == "file"
    assert len(config.members) == 4


# ---------------------------------------------------------------------------
# Member fields feeding subprocess argv: id / model / effort
# ---------------------------------------------------------------------------

def test_council_member_path_traversal_id_raises():
    with pytest.raises(ValidationError):
        CouncilMember(id="../../../../etc/passwd", backend="claude")


def test_council_member_flag_injection_model_raises():
    with pytest.raises(ValidationError):
        CouncilMember(id="claude", backend="claude", model="--dangerously-skip-permissions")


def test_council_member_shell_injection_effort_raises():
    with pytest.raises(ValidationError):
        CouncilMember(id="claude", backend="claude", effort="; rm -rf ~")


def test_council_member_valid_id_model_effort_pass():
    member = CouncilMember(id="claude-2", backend="claude", model="claude-sonnet-4.5", effort="high")

    assert member.id == "claude-2"
    assert member.model == "claude-sonnet-4.5"
    assert member.effort == "high"


def test_council_member_oversized_model_raises():
    with pytest.raises(ValidationError):
        CouncilMember(id="claude", backend="claude", model="a" * (MAX_MODEL_CHARS + 1))


def test_council_member_oversized_effort_raises():
    with pytest.raises(ValidationError):
        CouncilMember(id="claude", backend="claude", effort="a" * (MAX_EFFORT_CHARS + 1))


# ---------------------------------------------------------------------------
# Malformed YAML edge cases must never surface a raw Python exception
# ---------------------------------------------------------------------------

def test_load_council_config_non_string_yaml_key_raises_council_config_error(tmp_path):
    _write_yaml(
        tmp_path,
        """
1: stray-value
version: 1
members:
  - {id: claude, backend: claude}
""",
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_broken_utf8_raises_council_config_error(tmp_path):
    council_config_path(tmp_path).write_bytes(b"version: 1\nmembers: []\n\xff\xfe")

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_deeply_nested_yaml_raises_council_config_error(tmp_path):
    nesting = 60000
    council_config_path(tmp_path).write_text("a: " + "[" * nesting + "]" * nesting, encoding="utf-8")

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


def test_load_council_config_oversized_file_raises_council_config_error(tmp_path):
    _write_yaml(
        tmp_path,
        "version: 1\nmembers:\n  - {id: claude, backend: claude}\n"
        + ("# padding\n" * (MAX_CONFIG_BYTES // len("# padding\n") + 1)),
    )

    with pytest.raises(CouncilConfigError):
        load_council_config(tmp_path)


# ---------------------------------------------------------------------------
# prompt field length cap
# ---------------------------------------------------------------------------

def test_council_config_oversized_prompt_raises():
    with pytest.raises(ValidationError):
        CouncilConfig(
            version=1,
            members=[CouncilMember(id="claude", backend="claude")],
            prompt="x" * (MAX_PROMPT_CHARS + 1),
        )
