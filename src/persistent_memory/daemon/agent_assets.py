"""Agent rule and memory asset inventory: read and edit CLAUDE.md, AGENTS.md,
memory files and settings from a single dashboard view.

Security model: clients never send filesystem paths. They send a structured
asset id (``claude:memory:<project>:<file>``) and the daemon rebuilds the path
from known roots, so path traversal has no attack surface. Both the inventory
and the resolver are derived from the same ``ASSET_SOURCES`` table, so a file
that the inventory cannot list can never be resolved either. Reads are narrower
than the extension allowlist (exact filenames, or ``.md`` files that really
exist in a scanned directory) and writes are narrower still: credential and
settings files are read-only. Resolved paths are realpath-checked against their
root to close the symlink escape.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from persistent_memory.transcripts import (
    CODEX_ROOT,
    GROK_ROOT,
    PROJECTS_ROOT,
)

CLAUDE_ROOT = Path.home() / ".claude"

ID_SEPARATOR = ":"
ID_SEGMENT_COUNT = 4
SAFE_SEGMENT_RE = re.compile(r"[\w.\-]+")
FORBIDDEN_SEGMENT_CHARS = ("/", "\\", "\x00")
CURRENT_SEGMENT = "."
PARENT_SEGMENT = ".."
GLOBAL_SCOPE = "global"

ALLOWED_SUFFIXES = frozenset({".md", ".json", ".toml", ".rules"})
SCANNED_SUFFIX = ".md"

MEMORY_DIRNAME = "memory"
CODEX_MEMORIES_DIRNAME = "memories"
CODEX_RULES_DIRNAME = "rules"
CODEX_RULES_FILENAME = "default.rules"

AGENT_CLAUDE = "claude"
AGENT_CODEX = "codex"
AGENT_GROK = "grok"

LAYER_RULES = "rules"
LAYER_MEMORY = "memory"
LAYER_SETTINGS = "settings"

CLAUDE_SETTINGS_FILENAMES = ("settings.json", "settings.local.json")
CLAUDE_RULES_FILENAMES = ("CLAUDE.md",)
CODEX_RULES_FILENAMES = ("AGENTS.md",)
GROK_RULES_FILENAMES = ("AGENTS.md",)


@dataclass(frozen=True)
class AssetRoots:
    claude_root: Path = field(default=CLAUDE_ROOT)
    projects_root: Path = field(default=PROJECTS_ROOT)
    codex_root: Path = field(default=CODEX_ROOT)
    grok_root: Path = field(default=GROK_ROOT)


@dataclass(frozen=True)
class AssetSource:
    """One (agent, layer) location. Empty ``filenames`` means the directory is
    scanned for ``.md`` files instead of matching fixed names."""

    agent: str
    layer: str
    filenames: tuple[str, ...] = ()
    subdir: tuple[str, ...] = ()
    scoped: bool = False
    writable: bool = True

    @property
    def is_scanned(self) -> bool:
        return not self.filenames


ASSET_SOURCES: tuple[AssetSource, ...] = (
    AssetSource(AGENT_CLAUDE, LAYER_RULES, CLAUDE_RULES_FILENAMES),
    AssetSource(AGENT_CLAUDE, LAYER_SETTINGS, CLAUDE_SETTINGS_FILENAMES, writable=False),
    AssetSource(AGENT_CLAUDE, LAYER_MEMORY, scoped=True),
    AssetSource(AGENT_CODEX, LAYER_RULES, CODEX_RULES_FILENAMES),
    AssetSource(
        AGENT_CODEX,
        LAYER_RULES,
        (CODEX_RULES_FILENAME,),
        subdir=(CODEX_RULES_DIRNAME,),
    ),
    AssetSource(AGENT_CODEX, LAYER_MEMORY, subdir=(CODEX_MEMORIES_DIRNAME,)),
    AssetSource(AGENT_GROK, LAYER_RULES, GROK_RULES_FILENAMES),
)


def is_safe_segment(segment: str) -> bool:
    if not segment or segment in (CURRENT_SEGMENT, PARENT_SEGMENT):
        return False
    if any(char in segment for char in FORBIDDEN_SEGMENT_CHARS):
        return False
    return SAFE_SEGMENT_RE.fullmatch(segment) is not None


def _validate_segment(segment: str) -> None:
    if not is_safe_segment(segment):
        raise ValueError(f"unsafe asset id segment: {segment!r}")


def _root_for(agent: str, roots: AssetRoots) -> Path:
    if agent == AGENT_CLAUDE:
        return roots.claude_root
    if agent == AGENT_CODEX:
        return roots.codex_root
    if agent == AGENT_GROK:
        return roots.grok_root
    raise ValueError(f"unknown agent: {agent}")


def _source_dir(source: AssetSource, scope: str, roots: AssetRoots) -> Path:
    if source.scoped:
        return roots.projects_root / scope / MEMORY_DIRNAME
    base = _root_for(source.agent, roots)
    for part in source.subdir:
        base = base / part
    return base


def _within_root(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def resolve_asset_path(
    asset_id: str,
    roots: AssetRoots | None = None,
    *,
    for_write: bool = False,
) -> Path:
    """Turn a structured asset id into an absolute path under a known root."""
    roots = roots or AssetRoots()
    parts = asset_id.split(ID_SEPARATOR)
    if len(parts) != ID_SEGMENT_COUNT:
        raise ValueError(f"malformed asset id: {asset_id!r}")
    agent, layer, scope, name = parts
    for segment in (agent, layer, scope, name):
        _validate_segment(segment)

    candidate: Path | None = None
    scanned_miss = False
    for source in ASSET_SOURCES:
        if source.agent != agent or source.layer != layer:
            continue
        if not source.scoped and scope != GLOBAL_SCOPE:
            continue
        if source.is_scanned:
            if not name.endswith(SCANNED_SUFFIX):
                continue
        elif name not in source.filenames:
            continue
        if for_write and not source.writable:
            raise ValueError(f"asset is read-only: {asset_id!r}")
        path = _source_dir(source, scope, roots) / name
        if source.is_scanned and not (path.is_file() or path.is_symlink()):
            scanned_miss = True
            continue
        candidate = path
        break

    if candidate is None:
        if scanned_miss:
            raise FileNotFoundError(asset_id)
        raise ValueError(f"asset not allowed: {asset_id!r}")

    if candidate.suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"extension not allowed: {candidate.suffix!r}")

    if (candidate.exists() or candidate.is_symlink()) and not _within_root(
        candidate, candidate.parent
    ):
        raise ValueError(f"asset escapes its root: {asset_id!r}")
    return candidate


def _describe(path: Path, asset_id: str, agent: str, layer: str, scope: str) -> dict:
    stat = path.stat()
    return {
        "id": asset_id,
        "agent": agent,
        "layer": layer,
        "scope": scope,
        "name": path.name,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _collect_source(source: AssetSource, scope: str, roots: AssetRoots) -> list[dict]:
    directory = _source_dir(source, scope, roots)
    names: list[str]
    if source.is_scanned:
        if not directory.is_dir():
            return []
        names = sorted(p.name for p in directory.glob(f"*{SCANNED_SUFFIX}"))
    else:
        names = list(source.filenames)

    found = []
    for name in names:
        if not is_safe_segment(name):
            continue
        path = directory / name
        if not path.is_file() or not _within_root(path, directory):
            continue
        asset_id = ID_SEPARATOR.join((source.agent, source.layer, scope, name))
        found.append(_describe(path, asset_id, source.agent, source.layer, scope))
    return found


def build_inventory(roots: AssetRoots | None = None) -> dict:
    """Scan every known root and return the flat asset list plus group summaries."""
    roots = roots or AssetRoots()
    assets: list[dict] = []

    for source in ASSET_SOURCES:
        if not source.scoped:
            assets.extend(_collect_source(source, GLOBAL_SCOPE, roots))
            continue
        if not roots.projects_root.is_dir():
            continue
        for project_dir in sorted(roots.projects_root.iterdir()):
            if not project_dir.is_dir() or not is_safe_segment(project_dir.name):
                continue
            assets.extend(_collect_source(source, project_dir.name, roots))

    groups: dict[tuple[str, str, str], dict] = {}
    for asset in assets:
        key = (asset["agent"], asset["layer"], asset["scope"])
        group = groups.setdefault(
            key,
            {
                "agent": asset["agent"],
                "layer": asset["layer"],
                "scope": asset["scope"],
                "count": 0,
                "size": 0,
                "mtime": asset["mtime"],
            },
        )
        group["count"] += 1
        group["size"] += asset["size"]
        if asset["mtime"] > group["mtime"]:
            group["mtime"] = asset["mtime"]

    return {
        "assets": assets,
        "groups": sorted(groups.values(), key=lambda g: (g["agent"], g["layer"], g["scope"])),
    }


BACKUP_SUBPATH = ("backups", "agent-assets")
BACKUP_ROOT = CLAUDE_ROOT.joinpath(*BACKUP_SUBPATH)
BACKUP_DIR_MODE = 0o700
BACKUP_STAMP_FORMAT = "%Y%m%dT%H%M%S%f"
TEMP_SUFFIX = ".pm-tmp"
TEMP_FILE_MODE = 0o600
MODE_MASK = 0o7777
ENCODING = "utf-8"


def default_backup_root(roots: AssetRoots | None = None) -> Path:
    """Backups live under the agent home, never inside this git repository."""
    roots = roots or AssetRoots()
    return roots.claude_root.joinpath(*BACKUP_SUBPATH)


def read_asset(asset_id: str, roots: AssetRoots | None = None) -> str:
    path = resolve_asset_path(asset_id, roots)
    if not path.is_file():
        raise FileNotFoundError(asset_id)
    return path.read_text(encoding=ENCODING)


def write_asset(
    asset_id: str,
    content: str,
    roots: AssetRoots | None = None,
    backup_root: Path | None = None,
) -> dict:
    """Back up the current file, then replace it atomically, preserving both the
    original permissions and any symlink that points at the real target."""
    roots = roots or AssetRoots()
    path = resolve_asset_path(asset_id, roots, for_write=True)
    if not path.is_file():
        raise FileNotFoundError(asset_id)
    target = path.resolve()

    backup_root = Path(backup_root) if backup_root else default_backup_root(roots)
    backup_root.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_root, BACKUP_DIR_MODE)
    stamp = datetime.now(timezone.utc).strftime(BACKUP_STAMP_FORMAT)
    backup_dir = backup_root / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, BACKUP_DIR_MODE)
    backup_path = backup_dir / f"{asset_id.replace(ID_SEPARATOR, '_')}"
    shutil.copy2(target, backup_path)

    mode = target.stat().st_mode & MODE_MASK
    temp_path = target.with_name(f".{target.name}{TEMP_SUFFIX}")
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, TEMP_FILE_MODE)
        with os.fdopen(fd, "w", encoding=ENCODING) as handle:
            handle.write(content)
        os.chmod(temp_path, mode)
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return {"id": asset_id, "size": target.stat().st_size, "backup": str(backup_path)}


def default_roots() -> AssetRoots:
    """Indirection point so tests can swap roots without touching the filesystem."""
    return AssetRoots()


class AssetBody(BaseModel):
    content: str


def register_agent_asset_routes(app, cfg, require_token) -> None:
    from fastapi import Depends, HTTPException

    @app.get("/api/agent-assets", dependencies=[Depends(require_token)])
    def list_agent_assets():
        return build_inventory(default_roots())

    @app.get("/api/agent-assets/{asset_id}/raw", dependencies=[Depends(require_token)])
    def read_agent_asset(asset_id: str):
        try:
            return {"id": asset_id, "content": read_asset(asset_id, default_roots())}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=asset_id) from exc

    @app.post("/api/agent-assets/{asset_id}", dependencies=[Depends(require_token)])
    def save_agent_asset(asset_id: str, body: AssetBody):
        roots = default_roots()
        try:
            return write_asset(asset_id, body.content, roots, default_backup_root(roots))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=asset_id) from exc
