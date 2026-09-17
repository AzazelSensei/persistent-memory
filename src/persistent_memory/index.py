"""Generates the human-readable index.md catalog for a record corpus.

Groups records by type, sorts each section by date (newest first), and
marks superseded records inline. The index file itself is a derived
artifact and is skipped by record collection.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .i18n import t
from .lint import INDEX_FILENAME, LoadedRecord
from .schema import RecordType, parse_document

HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
TITLE_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
ORDERED_ITEM_RE = re.compile(r"^\d+[.)]\s")
PROSE_SKIP_PREFIXES = ("#", ">", "-", "*", "|", "`", "=", "~", "<!--", "![", "[")
MAX_DERIVED_TITLE_CHARS = 120
SECTION_LABEL_PREFIXES = (
    "context",
    "bağlam",
    "decision",
    "karar",
    "rationale",
    "gerekçe",
    "outcome",
    "sonuç",
    "source",
    "kaynak",
    "what happened",
    "ne oldu",
    "why",
    "neden",
    "when discovered",
    "ne zaman",
    "general rule",
    "genel kural",
    "lesson",
    "evidence",
    "kök neden",
    "nasıl uygulanır",
    "doğrulama",
)


def _is_section_label(heading: str) -> bool:
    """True when the heading is a canonical body section, not a real title.

    Turkish dotless-i is folded explicitly: `str.casefold` maps `I` to `i`,
    so an all-caps `NASIL UYGULANIR` would otherwise miss its prefix.
    """
    normalized = heading.replace("I", "ı").replace("İ", "i").casefold().strip()
    return normalized.startswith(SECTION_LABEL_PREFIXES)


def _first_prose_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(PROSE_SKIP_PREFIXES):
            continue
        if ORDERED_ITEM_RE.match(stripped):
            continue
        return stripped[:MAX_DERIVED_TITLE_CHARS]
    return ""


def _extract_title(loaded: LoadedRecord) -> str:
    """Title for catalog rows and recall lines.

    An H1 is always the author's title and wins outright. Only when a record
    has no H1 does the first heading get inspected: if it is a section label
    ("## Context / Problem") it would spend a recall slot saying nothing, so
    the opening prose line is used instead.
    """
    title = TITLE_HEADING_RE.search(loaded.body)
    if title:
        return title.group(1)
    match = HEADING_RE.search(loaded.body)
    if not match:
        return loaded.path.stem
    heading = match.group(1)
    if not _is_section_label(heading):
        return heading
    return _first_prose_line(loaded.body) or loaded.path.stem


def format_index_row(loaded: LoadedRecord) -> str:
    """Render one catalog line: id, title, status, date, supersession marker."""
    record = loaded.record
    title = _extract_title(loaded)
    suffix = ""
    if record.superseded_by:
        suffix = f" → ~~superseded by {', '.join(record.superseded_by)}~~"
    return (
        f"- `{record.id}` **{title}** "
        f"`[{record.status.value}]` ({record.date}){suffix}"
    )


def _section_rows(loaded_items: list[LoadedRecord], record_type: RecordType) -> list[str]:
    rows = [item for item in loaded_items if item.record.type is record_type]
    rows.sort(key=lambda item: item.record.date, reverse=True)
    if not rows:
        return [t("index.empty_section")]
    return [format_index_row(item) for item in rows]


def _collect_records_resilient(directory: Path) -> list[LoadedRecord]:
    # Malformed records are skipped, not fatal: the index must stay
    # buildable while lint reports the broken files.
    if not directory.is_dir():
        raise NotADirectoryError(f"corpus directory not found: {directory}")
    loaded: list[LoadedRecord] = []
    for md_path in sorted(directory.glob("*.md")):
        if md_path.name == INDEX_FILENAME:
            continue
        text = md_path.read_text(encoding="utf-8")
        try:
            record, body = parse_document(text)
        except ValueError:
            continue
        loaded.append(LoadedRecord(record=record, path=md_path, body=body))
    return loaded


SECTION_TYPE_KEY = {
    RecordType.DECISION: "index.section.decisions",
    RecordType.LESSON: "index.section.lessons",
    RecordType.PRINCIPLE: "index.section.principles",
}


def build_index_markdown(directory: Path) -> str:
    """Build the full catalog markdown for all parseable records in a directory."""
    loaded = _collect_records_resilient(directory)
    lines = [t("index.title"), "", t("index.total").format(count=len(loaded)), ""]
    for record_type, section_key in SECTION_TYPE_KEY.items():
        lines.append(t(section_key))
        lines.extend(_section_rows(loaded, record_type))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


WRITE_FLAG = "--write"
EXIT_USAGE = 2
USAGE = "usage: python -m persistent_memory.index <directory> [--write]"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    should_write = WRITE_FLAG in args
    positional = [arg for arg in args if arg != WRITE_FLAG]
    if len(positional) != 1:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    directory = Path(positional[0])
    markdown = build_index_markdown(directory)
    if should_write:
        (directory / INDEX_FILENAME).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
