import plistlib
from pathlib import Path

from persistent_memory.daemon.launch_agent import (
    LAUNCH_AGENT_LABEL,
    build_launch_agent_plist,
)


def test_plist_lang_none_omits_environment_variables():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
        lang=None,
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    assert "EnvironmentVariables" not in parsed


def test_plist_lang_set_adds_pm_lang_env():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
        lang="tr",
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    assert "EnvironmentVariables" in parsed
    assert parsed["EnvironmentVariables"]["PM_LANG"] == "tr"


def test_plist_lang_en_adds_pm_lang_env():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
        lang="en",
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    assert "EnvironmentVariables" in parsed
    assert parsed["EnvironmentVariables"]["PM_LANG"] == "en"


def test_plist_lang_none_is_default():
    raw_no_arg = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
    )
    raw_explicit_none = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
        lang=None,
    )
    assert raw_no_arg == raw_explicit_none


def test_plist_is_valid_and_has_label():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    assert parsed["Label"] == LAUNCH_AGENT_LABEL
    assert parsed["KeepAlive"] == {"SuccessfulExit": False}
    assert parsed["RunAtLoad"] is True
    assert parsed["ThrottleInterval"] >= 10


def test_plist_captures_daemon_logs_under_user_logs_dir():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    log_dir = Path.home() / "Library/Logs/persistent-memory"
    assert parsed["StandardErrorPath"] == str(log_dir / "daemon.err.log")
    assert parsed["StandardOutPath"] == str(log_dir / "daemon.out.log")


def test_plist_can_capture_daemon_logs_under_target_home():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
        home_dir="/Users/target",
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    assert (
        parsed["StandardErrorPath"]
        == "/Users/target/Library/Logs/persistent-memory/daemon.err.log"
    )
    assert (
        parsed["StandardOutPath"]
        == "/Users/target/Library/Logs/persistent-memory/daemon.out.log"
    )


def test_plist_program_args_run_uvicorn_on_loopback():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    args = parsed["ProgramArguments"]
    assert args[0] == "/Users/x/.venv/bin/python"
    joined = " ".join(args)
    assert "uvicorn" in joined
    assert "127.0.0.1" in joined
    assert "37778" in joined


def test_plist_sets_working_directory():
    raw = build_launch_agent_plist(
        python_bin="/Users/x/.venv/bin/python",
        working_dir="/Users/x/proj",
    )
    parsed = plistlib.loads(raw.encode("utf-8"))
    assert parsed["WorkingDirectory"] == "/Users/x/proj"
