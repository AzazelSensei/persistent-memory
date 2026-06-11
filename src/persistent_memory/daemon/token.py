"""Per-install auth token and records-dir resolution.

The token is a random hex secret stored owner-only (0600) under
``.pm-index/daemon.token``. Hooks and the dashboard read it from disk and
send it in the X-PM-Token header for mutating endpoints; since browsers
cannot attach custom headers cross-site, the same token serves as the CSRF
defense for the loopback-only daemon.
"""

import os
import secrets
from pathlib import Path

TOKEN_DIRNAME = ".pm-index"
TOKEN_FILENAME = "daemon.token"
TOKEN_BYTES = 32
TOKEN_FILE_MODE = 0o600
RECORDS_DIR_ENV = "PM_RECORDS_DIR"
DEFAULT_RECORDS_SUBDIR = "docs"


def token_path(records_dir: Path) -> Path:
    return Path(records_dir) / TOKEN_DIRNAME / TOKEN_FILENAME


def _install_anchored_records_dir() -> Path | None:
    root = Path(__file__).resolve().parents[3]
    candidate = root / DEFAULT_RECORDS_SUBDIR
    return candidate if candidate.is_dir() else None


def default_records_dir() -> Path:
    override = os.environ.get(RECORDS_DIR_ENV)
    if override:
        return Path(override)
    anchored = _install_anchored_records_dir()
    if anchored is not None:
        return anchored
    return Path.cwd() / DEFAULT_RECORDS_SUBDIR


def read_token(records_dir: Path) -> str | None:
    path = token_path(records_dir)
    if not path.exists():
        return None
    token = path.read_text(encoding="utf-8").strip()
    return token or None


def load_or_create_token(records_dir: Path) -> str:
    path = token_path(records_dir)
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(TOKEN_BYTES)
    path.write_text(token, encoding="utf-8")
    path.chmod(TOKEN_FILE_MODE)
    return token
