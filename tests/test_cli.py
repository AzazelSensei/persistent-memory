import subprocess
import sys

from tests.test_collect_records import VALID_DECISION, write_record


def run_module(module, *args):
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True, text=True,
    )


def test_lint_cli_exits_zero_on_clean_corpus(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    result = run_module("persistent_memory.lint", str(tmp_path))
    assert result.returncode == 0


def test_lint_cli_exits_one_and_prints_findings_on_broken(tmp_path):
    write_record(tmp_path, "a.md", VALID_DECISION)
    write_record(tmp_path, "b.md", VALID_DECISION)
    result = run_module("persistent_memory.lint", str(tmp_path))
    assert result.returncode == 1
    assert "duplicate-id" in result.stdout


def test_index_cli_prints_catalog(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    result = run_module("persistent_memory.index", str(tmp_path))
    assert result.returncode == 0
    assert "D-0001" in result.stdout


def test_index_cli_write_flag_creates_index_md(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    result = run_module("persistent_memory.index", str(tmp_path), "--write")
    assert result.returncode == 0
    assert (tmp_path / "index.md").read_text(encoding="utf-8").find("D-0001") >= 0
