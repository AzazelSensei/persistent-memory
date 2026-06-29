"""TDD: derive_project_and_branch — worktree-aware project/branch derivation.

Tests use real git repos and worktrees (via subprocess) to validate the full
derivation rules:
  - Normal git repo: project=basename(cwd), branch=current branch
  - Worktree root: project=main repo name, branch=worktree branch
  - Subdirectory inside worktree: project=basename(subdir), branch=worktree branch
  - Non-git dir: project=basename(cwd), branch=None
"""

import os
import subprocess
from pathlib import Path

import pytest

from persistent_memory.hooks.common import derive_project_and_branch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
    )


def _init_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test User")
    _git(path, "commit", "--allow-empty", "-m", "initial")
    return path


# ---------------------------------------------------------------------------
# Non-git directory
# ---------------------------------------------------------------------------

def test_non_git_dir_uses_basename_no_branch(tmp_path):
    non_git = tmp_path / "myproject"
    non_git.mkdir()
    project, branch = derive_project_and_branch(str(non_git))
    assert project == "myproject"
    assert branch is None


def test_empty_cwd_returns_unknown_no_branch():
    project, branch = derive_project_and_branch("")
    assert project == "unknown"
    assert branch is None


# ---------------------------------------------------------------------------
# Normal git repo (not a worktree)
# ---------------------------------------------------------------------------

def test_normal_repo_project_is_basename(tmp_path):
    repo = tmp_path / "BlackHoleLabs"
    _init_repo(repo, branch="main")
    project, branch = derive_project_and_branch(str(repo))
    assert project == "BlackHoleLabs"


def test_normal_repo_branch_is_current_branch(tmp_path):
    repo = tmp_path / "BlackHoleLabs"
    _init_repo(repo, branch="main")
    project, branch = derive_project_and_branch(str(repo))
    assert branch == "main"


def test_normal_repo_subdirectory_uses_subdir_basename(tmp_path):
    repo = tmp_path / "BlackHoleLabs"
    _init_repo(repo, branch="develop")
    subdir = repo / "backend"
    subdir.mkdir()
    project, branch = derive_project_and_branch(str(subdir))
    assert project == "backend"
    assert branch == "develop"


# ---------------------------------------------------------------------------
# Linked worktree root — project = main repo name, branch = worktree branch
# ---------------------------------------------------------------------------

def test_worktree_root_project_is_main_repo_name(tmp_path):
    repo = tmp_path / "BlackHoleLabs"
    _init_repo(repo, branch="main")
    wt_path = tmp_path / "BlackHoleLabs" / ".worktrees" / "faz1-backend"
    # Create a new branch for the worktree
    _git(repo, "checkout", "-b", "faz1-backend")
    _git(repo, "checkout", "main")
    _git(repo, "worktree", "add", str(wt_path), "faz1-backend")

    project, branch = derive_project_and_branch(str(wt_path))
    assert project == "BlackHoleLabs"
    assert branch == "faz1-backend"


def test_worktree_subdirectory_uses_subdir_basename(tmp_path):
    repo = tmp_path / "BlackHoleLabs"
    _init_repo(repo, branch="main")
    wt_path = tmp_path / "BlackHoleLabs" / ".worktrees" / "faz1-backend"
    _git(repo, "checkout", "-b", "faz1-backend")
    _git(repo, "checkout", "main")
    _git(repo, "worktree", "add", str(wt_path), "faz1-backend")

    subdir = wt_path / "src"
    subdir.mkdir()
    project, branch = derive_project_and_branch(str(subdir))
    # Subdirectory inside worktree: project = basename(subdir), NOT main repo name
    assert project == "src"
    assert branch == "faz1-backend"


# ---------------------------------------------------------------------------
# Error handling — git failures are silent
# ---------------------------------------------------------------------------

def test_git_error_falls_back_gracefully(tmp_path, monkeypatch):
    non_git = tmp_path / "myproject"
    non_git.mkdir()

    def fail_run(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", fail_run)
    project, branch = derive_project_and_branch(str(non_git))
    assert project == "myproject"
    assert branch is None
