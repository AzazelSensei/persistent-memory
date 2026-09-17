"""Tests for the AI Council CLI call layer: env hygiene, argv, answer extraction."""

import json

import pytest

from persistent_memory.council.backends import (
    COUNCIL_ENV_ALLOWLIST,
    COUNCIL_READONLY_ENV,
    CouncilBackendError,
    build_council_argv,
    build_council_env,
    extract_answer,
    resolve_backend_bin,
)

# ---------------------------------------------------------------------------
# build_council_env — allowlist is the only pass-through path, PATH extension
# ---------------------------------------------------------------------------


def test_build_council_env_sensitive_vars_do_not_pass_through(monkeypatch):
    # These are the vars real nested-CLI auth breakage was traced to (see
    # module docstring / design doc section 8) — they must never reach the
    # child process regardless of what mechanism keeps them out.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://leaked.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-leaked")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_AGENT_SDK_VERSION", "9.9.9")

    env = build_council_env()

    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDECODE" not in env
    assert "CLAUDE_AGENT_SDK_VERSION" not in env


def test_build_council_env_claude_code_prefixed_keys_never_pass(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "leaked")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "leaked")

    env = build_council_env()

    assert not any(key.startswith("CLAUDE_CODE_") for key in env)


def test_build_council_env_allowlist_keys_pass_through(monkeypatch):
    for key in COUNCIL_ENV_ALLOWLIST:
        monkeypatch.setenv(key, f"value-{key}")

    env = build_council_env()

    for key in COUNCIL_ENV_ALLOWLIST:
        if key == "PATH":
            assert env[key].endswith("value-PATH")
            continue
        assert env[key] == f"value-{key}"


def test_build_council_env_unlisted_keys_do_not_pass(monkeypatch):
    monkeypatch.setenv("SOME_RANDOM_VAR", "should-not-leak")

    env = build_council_env()

    assert "SOME_RANDOM_VAR" not in env


def test_build_council_env_pm_prefixed_vars_pass_through(monkeypatch):
    monkeypatch.setenv("PM_CODEX_BIN", "/custom/codex")

    env = build_council_env()

    assert env["PM_CODEX_BIN"] == "/custom/codex"


def test_build_council_env_path_extended_with_council_extra_paths(monkeypatch, tmp_path):
    extra_dir = tmp_path / "extra-bin"
    extra_dir.mkdir()
    monkeypatch.setattr("persistent_memory.council.backends.COUNCIL_EXTRA_PATHS", (extra_dir,))
    monkeypatch.setenv("PATH", "/usr/bin")

    env = build_council_env()

    assert str(extra_dir) in env["PATH"].split(":")
    assert "/usr/bin" in env["PATH"].split(":")


def test_build_council_env_skips_nonexistent_extra_paths(monkeypatch, tmp_path):
    missing_dir = tmp_path / "does-not-exist"
    monkeypatch.setattr("persistent_memory.council.backends.COUNCIL_EXTRA_PATHS", (missing_dir,))
    monkeypatch.setenv("PATH", "/usr/bin")

    env = build_council_env()

    assert str(missing_dir) not in env["PATH"].split(":")


# ---------------------------------------------------------------------------
# MUST-FIX 5 — the read-only guard flag always reaches the member subprocess
# ---------------------------------------------------------------------------


def test_build_council_env_sets_readonly_flag():
    env = build_council_env()

    assert env[COUNCIL_READONLY_ENV] == "1"


def test_build_council_env_readonly_flag_cannot_be_unset_by_parent_env(monkeypatch):
    monkeypatch.setenv(COUNCIL_READONLY_ENV, "0")

    env = build_council_env()

    assert env[COUNCIL_READONLY_ENV] == "1"


# ---------------------------------------------------------------------------
# resolve_backend_bin — mirrors daemon/services.py _resolve_*_bin
# ---------------------------------------------------------------------------


def test_resolve_backend_bin_claude_uses_which(monkeypatch):
    monkeypatch.setattr(
        "persistent_memory.council.backends.shutil.which",
        lambda name, path=None: "/usr/local/bin/claude" if name == "claude" else None,
    )

    assert resolve_backend_bin("claude", env={"PATH": "/usr/local/bin"}) == "/usr/local/bin/claude"


def test_resolve_backend_bin_claude_falls_back_to_bare_name(monkeypatch):
    monkeypatch.setattr("persistent_memory.council.backends.shutil.which", lambda name, path=None: None)

    assert resolve_backend_bin("claude", env={}) == "claude"


def test_resolve_backend_bin_codex_env_override_wins(monkeypatch):
    monkeypatch.setattr("persistent_memory.council.backends.shutil.which", lambda name, path=None: None)

    result = resolve_backend_bin("codex", env={"PM_CODEX_BIN": "/opt/codex-custom"})

    assert result == "/opt/codex-custom"


def test_resolve_backend_bin_codex_app_bin_preferred_over_which(monkeypatch, tmp_path):
    fake_app_bin = tmp_path / "codex-app-bin"
    fake_app_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr("persistent_memory.council.backends.CODEX_APP_BIN", fake_app_bin)
    monkeypatch.setattr(
        "persistent_memory.council.backends.shutil.which",
        lambda name, path=None: "/usr/bin/codex",
    )

    assert resolve_backend_bin("codex", env={}) == str(fake_app_bin)


def test_resolve_backend_bin_codex_falls_back_to_which(monkeypatch, tmp_path):
    monkeypatch.setattr("persistent_memory.council.backends.CODEX_APP_BIN", tmp_path / "missing")
    monkeypatch.setattr(
        "persistent_memory.council.backends.shutil.which",
        lambda name, path=None: "/usr/bin/codex",
    )

    assert resolve_backend_bin("codex", env={}) == "/usr/bin/codex"


def test_resolve_backend_bin_codex_returns_none_when_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("persistent_memory.council.backends.CODEX_APP_BIN", tmp_path / "missing")
    monkeypatch.setattr("persistent_memory.council.backends.shutil.which", lambda name, path=None: None)

    assert resolve_backend_bin("codex", env={}) is None


def test_resolve_backend_bin_kimi_uses_which(monkeypatch):
    monkeypatch.setattr(
        "persistent_memory.council.backends.shutil.which",
        lambda name, path=None: "/usr/local/bin/kimi" if name == "kimi" else None,
    )

    assert resolve_backend_bin("kimi", env={}) == "/usr/local/bin/kimi"


def test_resolve_backend_bin_grok_env_override_wins(monkeypatch):
    monkeypatch.setattr("persistent_memory.council.backends.shutil.which", lambda name, path=None: None)

    result = resolve_backend_bin("grok", env={"PM_GROK_BIN": "/opt/grok-custom"})

    assert result == "/opt/grok-custom"


def test_resolve_backend_bin_grok_prefers_user_bin(monkeypatch, tmp_path):
    user_bin = tmp_path / "grok-user"
    user_bin.write_text("#!/bin/sh\n")
    home_bin = tmp_path / "grok-home"
    home_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr("persistent_memory.council.backends.GROK_USER_BIN", user_bin)
    monkeypatch.setattr("persistent_memory.council.backends.GROK_HOME_BIN", home_bin)
    monkeypatch.setattr("persistent_memory.council.backends.shutil.which", lambda name, path=None: None)

    assert resolve_backend_bin("grok", env={}) == str(user_bin.resolve())


def test_resolve_backend_bin_grok_falls_back_to_which(monkeypatch, tmp_path):
    monkeypatch.setattr("persistent_memory.council.backends.GROK_USER_BIN", tmp_path / "missing-user")
    monkeypatch.setattr("persistent_memory.council.backends.GROK_HOME_BIN", tmp_path / "missing-home")
    monkeypatch.setattr(
        "persistent_memory.council.backends.shutil.which",
        lambda name, path=None: "/usr/bin/grok",
    )

    assert resolve_backend_bin("grok", env={}) == "/usr/bin/grok"


def test_resolve_backend_bin_unknown_backend_raises():
    with pytest.raises(CouncilBackendError):
        resolve_backend_bin("mystery", env={})


# ---------------------------------------------------------------------------
# build_council_argv — exact flag order per backend
# ---------------------------------------------------------------------------


def test_build_council_argv_claude_without_model():
    argv = build_council_argv("claude", "do the thing", "/repo")

    assert argv == [
        "claude",
        "-p",
        "do the thing",
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
        "--add-dir",
        "/repo",
    ]


def test_build_council_argv_claude_with_model():
    argv = build_council_argv("claude", "do the thing", "/repo", model="claude-opus-4-8")

    assert argv == [
        "claude",
        "-p",
        "do the thing",
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
        "--model",
        "claude-opus-4-8",
        "--add-dir",
        "/repo",
    ]


def test_build_council_argv_claude_never_uses_strict_mcp_config():
    argv = build_council_argv("claude", "prompt", "/repo", model="m")

    assert "--strict-mcp-config" not in argv


def test_build_council_argv_codex_minimal():
    argv = build_council_argv("codex", "the prompt", "/repo")

    assert argv == [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        "/repo",
        "--dangerously-bypass-approvals-and-sandbox",
        "the prompt",
    ]


def test_build_council_argv_codex_with_model_and_effort():
    argv = build_council_argv("codex", "the prompt", "/repo", model="gpt-5.5", effort="xhigh")

    assert argv == [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        "/repo",
        "--dangerously-bypass-approvals-and-sandbox",
        "-m",
        "gpt-5.5",
        "-c",
        f"model_reasoning_effort={json.dumps('xhigh')}",
        "the prompt",
    ]


def test_build_council_argv_kimi_minimal():
    argv = build_council_argv("kimi", "the prompt", "/repo")

    assert argv == ["kimi", "-p", "the prompt", "--output-format", "text"]


def test_build_council_argv_kimi_with_model():
    argv = build_council_argv("kimi", "the prompt", "/repo", model="kimi-k2")

    assert argv == ["kimi", "-p", "the prompt", "--output-format", "text", "-m", "kimi-k2"]


def test_build_council_argv_kimi_never_uses_auto_or_yolo_flags():
    argv = build_council_argv("kimi", "the prompt", "/repo", model="kimi-k2")

    assert "-y" not in argv
    assert "--auto" not in argv


def test_build_council_argv_grok_minimal():
    argv = build_council_argv("grok", "the prompt", "/repo")

    assert argv == [
        "grok",
        "-p",
        "the prompt",
        "--always-approve",
        "--output-format",
        "plain",
        "--no-subagents",
        "--cwd",
        "/repo",
    ]


def test_build_council_argv_grok_with_model_and_effort():
    argv = build_council_argv("grok", "the prompt", "/repo", model="grok-4", effort="low")

    assert argv == [
        "grok",
        "-p",
        "the prompt",
        "--always-approve",
        "--output-format",
        "plain",
        "--no-subagents",
        "--effort",
        "low",
        "-m",
        "grok-4",
        "--cwd",
        "/repo",
    ]


def test_build_council_argv_unknown_backend_raises():
    with pytest.raises(CouncilBackendError):
        build_council_argv("mystery", "prompt", "/repo")


# ---------------------------------------------------------------------------
# extract_answer — backend-specific answer extraction
# ---------------------------------------------------------------------------


def test_extract_answer_claude_json_object_with_result_field():
    stdout = json.dumps({"type": "result", "result": "the council should adopt X", "cost_usd": 0.01})

    assert extract_answer("claude", stdout) == "the council should adopt X"


def test_extract_answer_claude_json_array_finds_result_entry():
    stdout = json.dumps(
        [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": []}},
            {"type": "result", "result": "final answer here", "is_error": False},
        ]
    )

    assert extract_answer("claude", stdout) == "final answer here"


def test_extract_answer_claude_unparseable_falls_back_to_raw_text():
    stdout = "not json at all, just a plain sentence."

    assert extract_answer("claude", stdout) == stdout


def test_extract_answer_claude_strips_whitespace_around_result():
    stdout = json.dumps({"type": "result", "result": "  padded answer  \n"})

    assert extract_answer("claude", stdout) == "padded answer"


def test_extract_answer_codex_takes_text_after_last_codex_tag():
    stdout = (
        "[2026-07-24T10:00:00] User instructions:\n"
        "do the thing\n\n"
        "[2026-07-24T10:00:05] codex\n"
        "I looked at the repo and here is my answer: adopt plan B.\n"
    )

    assert extract_answer("codex", stdout) == "I looked at the repo and here is my answer: adopt plan B."


def test_extract_answer_codex_bare_tag_line():
    stdout = "some preamble\ncodex\nthe real answer spans\nmultiple lines"

    assert extract_answer("codex", stdout) == "the real answer spans\nmultiple lines"


def test_extract_answer_codex_no_tag_falls_back_to_last_paragraph():
    stdout = "first paragraph of output\n\nsecond and final paragraph is the answer"

    assert extract_answer("codex", stdout) == "second and final paragraph is the answer"


def test_extract_answer_grok_returns_raw_text_with_preamble_untouched():
    stdout = (
        "I'll look up council_post on the persistent-memory MCP server, then call it "
        "with your exact arguments.Posted m-0002 to thread c-0007."
    )

    assert extract_answer("grok", stdout) == stdout


def test_extract_answer_grok_strips_leading_trailing_whitespace_only():
    stdout = "  \n  the actual grok answer  \n\n"

    assert extract_answer("grok", stdout) == "the actual grok answer"


def test_extract_answer_kimi_strips_whitespace():
    stdout = "\n  kimi's answer text  \n"

    assert extract_answer("kimi", stdout) == "kimi's answer text"


def test_extract_answer_empty_stdout_returns_empty_string_for_every_backend():
    for backend in ("claude", "codex", "kimi", "grok"):
        assert extract_answer(backend, "") == ""
        assert extract_answer(backend, "   \n\t  ") == ""


def test_extract_answer_unknown_backend_raises():
    with pytest.raises(CouncilBackendError):
        extract_answer("mystery", "some text")
