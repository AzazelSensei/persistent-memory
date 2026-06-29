"""macOS launchd agent plist for running the daemon at login."""

import plistlib
from pathlib import Path

from persistent_memory.daemon.config import DAEMON_HOST, DAEMON_PORT

LAUNCH_AGENT_LABEL = "com.persistent-memory.daemon"
UVICORN_APP_TARGET = "persistent_memory.daemon.__main__:app"
THROTTLE_INTERVAL_SECONDS = 10
LOG_SUBDIR = "Library/Logs/persistent-memory"
STDOUT_LOG_FILENAME = "daemon.out.log"
STDERR_LOG_FILENAME = "daemon.err.log"


def build_launch_agent_plist(
    *,
    python_bin: str,
    working_dir: str,
    lang: str | None = None,
    home_dir: str | None = None,
) -> str:
    base_home = Path(home_dir).expanduser() if home_dir is not None else Path.home()
    log_dir = base_home / LOG_SUBDIR
    config = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            python_bin,
            "-m",
            "uvicorn",
            UVICORN_APP_TARGET,
            "--host",
            DAEMON_HOST,
            "--port",
            str(DAEMON_PORT),
        ],
        "WorkingDirectory": working_dir,
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": THROTTLE_INTERVAL_SECONDS,
        "StandardOutPath": str(log_dir / STDOUT_LOG_FILENAME),
        "StandardErrorPath": str(log_dir / STDERR_LOG_FILENAME),
    }
    if lang is not None:
        config["EnvironmentVariables"] = {"PM_LANG": lang}
    return plistlib.dumps(config).decode("utf-8")
