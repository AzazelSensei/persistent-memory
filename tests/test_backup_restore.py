import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKUP = REPO / "scripts" / "backup.sh"
RESTORE = REPO / "scripts" / "restore.sh"


def run_script(script, *args):
    return subprocess.run(
        ["bash", str(script), *[str(a) for a in args]],
        capture_output=True,
        text=True,
    )


def make_source_tree(tmp_path):
    src = tmp_path / "docs"
    (src / "decisions").mkdir(parents=True)
    (src / "decisions" / "D-0001.md").write_text("x")
    return src


def test_backup_script_exists_and_executable():
    assert BACKUP.exists()
    assert os.access(BACKUP, os.X_OK)


def test_restore_script_exists_and_executable():
    assert RESTORE.exists()
    assert os.access(RESTORE, os.X_OK)


def test_backup_creates_tarball(tmp_path):
    src = make_source_tree(tmp_path)
    out = tmp_path / "snap.tar.gz"
    result = run_script(BACKUP, src, out)
    assert result.returncode == 0, result.stderr
    assert out.exists()


def test_backup_restore_round_trip(tmp_path):
    src = make_source_tree(tmp_path)
    (src / "decisions" / "D-0002.md").write_text("content-2")
    out = tmp_path / "snap.tar.gz"
    result = run_script(BACKUP, src, out)
    assert result.returncode == 0, result.stderr

    dest = tmp_path / "restored"
    dest.mkdir()
    result = run_script(RESTORE, out, dest)
    assert result.returncode == 0, result.stderr
    assert (dest / "docs" / "decisions" / "D-0001.md").read_text() == "x"
    assert (dest / "docs" / "decisions" / "D-0002.md").read_text() == "content-2"


def test_restore_missing_argument_fails():
    result = run_script(RESTORE)
    assert result.returncode != 0
    assert "usage" in result.stderr


def make_snapshot_and_live_target(tmp_path):
    src = make_source_tree(tmp_path)
    out = tmp_path / "snap.tar.gz"
    assert run_script(BACKUP, src, out).returncode == 0
    dest = tmp_path / "live"
    (dest / "docs" / "decisions").mkdir(parents=True)
    existing = dest / "docs" / "decisions" / "D-0001.md"
    existing.write_text("live-content")
    return out, dest, existing


def test_restore_refuses_existing_target_without_force(tmp_path):
    out, dest, existing = make_snapshot_and_live_target(tmp_path)
    result = run_script(RESTORE, out, dest)
    assert result.returncode != 0
    assert "--force" in result.stderr
    assert existing.read_text() == "live-content"


def test_restore_overwrites_existing_target_with_force(tmp_path):
    out, dest, existing = make_snapshot_and_live_target(tmp_path)
    result = run_script(RESTORE, out, dest, "--force")
    assert result.returncode == 0, result.stderr
    assert existing.read_text() == "x"
