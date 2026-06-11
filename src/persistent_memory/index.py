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


def _extract_title(loaded: LoadedRecord) -> str:
    match = HEADING_RE.search(loaded.body)
    if match:
        return match.group(1)
    return loaded.path.stem


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
