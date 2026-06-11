import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR_SRC = REPO_ROOT / "src" / "persistent_memory" / "doctor.py"
SRC_DIR = REPO_ROOT / "src"
THIRD_PARTY_IMPORTS = ("import httpx", "import pydantic", "from httpx", "from pydantic")
BARE_PYTHON = "python3"


def test_doctor_source_has_no_third_party_imports():
    source = DOCTOR_SRC.read_text()
    for needle in THIRD_PARTY_IMPORTS:
        assert needle not in source, needle


def _bare_python_without_deps() -> str | None:
    binary = shutil.which(BARE_PYTHON)
    if not binary:
        return None
    probe = subprocess.run(
        [binary, "-c", "import httpx"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return None
    return binary


def test_doctor_imports_under_bare_python3_without_deps():
    binary = _bare_python_without_deps()
    if binary is None:
        pytest.skip("no dependency-free system python3 available")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    result = subprocess.run(
        [binary, "-c", "import persistent_memory.doctor"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
