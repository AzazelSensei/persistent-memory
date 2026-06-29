"""One-shot migration: remap worktree-root records to correct project + branch.

For each record whose provenance.cwd is the root of a linked git worktree
(path matches "*/(.worktrees|.claude/worktrees)/<name>$"), update:
  - project  → basename of the main repository (parent of the worktrees dir)
  - provenance.branch → <name> (the worktree directory name)

Subdirectory cwds (.worktrees/<name>/sub/dir) are intentionally skipped:
their project granularity (e.g. "backend") is deliberate.

Usage:
  python scripts/migrate_worktree_projects.py [--apply] [docs/]
  --apply   Write changes to disk (default: dry-run, prints what would change)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

WORKTREE_ROOT_RE = re.compile(
    r"^(?P<parent>.+?)/(?:\.worktrees|\.claude/worktrees)/(?P<branch>[^/]+)$"
)

DOCS_DIRS = ["decisions", "lessons", "principles"]


def _abbrev_ref_from_disk(cwd: str) -> str | None:
    """Return HEAD branch name via git if the worktree still exists on disk."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            if ref and ref != "HEAD":
                return ref
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _infer_branch(cwd: str, path_branch: str) -> str:
    """Return branch name for a worktree record.

    The worktree directory name (path_branch) is always used as the canonical
    branch because it names the branch that was checked out at capture time.
    The disk git HEAD may have moved since then (worktree reused for a new
    branch), so we do NOT override the path-derived name with the live HEAD.
    Git is only consulted as a fallback when the path yields no useful name.
    """
    if path_branch:
        return path_branch
    disk_branch = _abbrev_ref_from_disk(cwd)
    return disk_branch if disk_branch is not None else path_branch


def _is_worktree_root(cwd: str) -> tuple[bool, str, str]:
    """Return (is_root, parent_basename, branch_name) for a given cwd."""
    m = WORKTREE_ROOT_RE.match(cwd)
    if not m:
        return False, "", ""
    parent = m.group("parent")
    branch = m.group("branch")
    return True, Path(parent).name, branch


def _parse_frontmatter_raw(text: str) -> tuple[dict, str, str] | None:
    """Parse frontmatter into (raw_dict, front_block, body).

    Returns None if the file does not start with ---.
    """
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        raw = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    return raw, parts[1], parts[2]


def _surgical_update(text: str, new_project: str, branch: str) -> str:
    """Apply minimal surgical changes to frontmatter text.

    Only modifies:
    - the `project:` line
    - adds `branch:` inside the `provenance:` block (after `agent:` line)

    Every other line is left byte-for-byte identical.
    """
    lines = text.split("\n")
    result: list[str] = []
    in_provenance = False
    branch_inserted = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Detect provenance block start
        if re.match(r"^provenance:\s*$", line):
            in_provenance = True
            result.append(line)
            continue

        # Inside provenance block: detect block end (unindented key or ---)
        if in_provenance:
            if line and not line[0].isspace() and not line.startswith(" "):
                # Exiting provenance block — insert branch before exit if not done
                if not branch_inserted:
                    result.append(f"  branch: {branch}")
                    branch_inserted = True
                in_provenance = False
            elif stripped.startswith("branch:"):
                # Already has branch — update it
                result.append(f"  branch: {branch}")
                branch_inserted = True
                continue
            elif stripped.startswith("agent:") and not branch_inserted:
                result.append(line)
                result.append(f"  branch: {branch}")
                branch_inserted = True
                continue

        # Update project line
        if re.match(r"^project:\s+", line):
            result.append(f"project: {new_project}")
            continue

        result.append(line)

    return "\n".join(result)


def migrate_record(
    path: Path,
    apply: bool,
) -> tuple[bool, str | None]:
    """Process one file.

    Returns (changed, description) where description explains the change
    or None if the file was skipped.
    """
    text = path.read_text(encoding="utf-8")
    parsed = _parse_frontmatter_raw(text)
    if parsed is None:
        return False, None

    raw, _front, _body = parsed
    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        return False, None

    cwd = provenance.get("cwd", "")
    if not cwd:
        return False, None

    is_root, parent_name, path_branch = _is_worktree_root(cwd)
    if not is_root:
        return False, None

    branch = _infer_branch(cwd, path_branch)
    new_project = parent_name
    current_project = str(raw.get("project", ""))
    current_branch = provenance.get("branch")

    project_changed = current_project != new_project
    branch_changed = current_branch != branch

    if not project_changed and not branch_changed:
        return False, None

    description = (
        f"{path.name}: project {current_project!r} → {new_project!r}"
        + (f", branch added: {branch!r}" if current_branch is None else f", branch {current_branch!r} → {branch!r}")
    )

    if apply:
        new_text = _surgical_update(text, new_project, branch)
        path.write_text(new_text, encoding="utf-8")

    return True, description


def find_record_files(docs_root: Path) -> list[Path]:
    files: list[Path] = []
    for subdir in DOCS_DIRS:
        d = docs_root / subdir
        if d.is_dir():
            files.extend(sorted(d.glob("*.md")))
    return files


def run(docs_root: Path, apply: bool) -> int:
    files = find_record_files(docs_root)
    changed: list[str] = []
    unchanged = 0

    for path in files:
        did_change, description = migrate_record(path, apply=apply)
        if did_change:
            changed.append(description)
        else:
            unchanged += 1

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] scanned {len(files)} files, {len(changed)} to change, {unchanged} unchanged")
    for desc in changed:
        marker = "  WROTE" if apply else "  WOULD"
        print(f"{marker}: {desc}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "docs",
        nargs="?",
        default="docs",
        help="path to the docs/ directory (default: docs/)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write changes to disk (default: dry-run)",
    )
    args = parser.parse_args(argv)

    docs_root = Path(args.docs)
    if not docs_root.is_dir():
        print(f"error: not a directory: {docs_root}", file=sys.stderr)
        return 1

    return run(docs_root, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
