"""Lifecycle operations for memory record files on disk.

Covers directory layout, sequential id allocation, atomic writes, record
creation from body templates, status updates, the immutability rule for
finalized records, and bidirectional supersession linking.
"""

import datetime
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from persistent_memory.schema import (
    ID_PATTERN,
    TYPE_TO_PREFIX,
    Provenance,
    Record,
    RecordStatus,
    RecordType,
    parse_document,
    serialize_document,
)

PREFIX_TO_TYPE = {prefix: rtype for rtype, prefix in TYPE_TO_PREFIX.items()}

DEFAULT_SALIENCE = 0.5

TYPE_TO_DIRNAME = {
    RecordType.DECISION: "decisions",
    RecordType.LESSON: "lessons",
    RecordType.PRINCIPLE: "principles",
}
ID_NUMBER_WIDTH = 4
FIRST_ID_NUMBER = 1


def dir_for_type(repo_root: Path, record_type: RecordType) -> Path:
    return repo_root / TYPE_TO_DIRNAME[record_type]


def ensure_dirs(repo_root: Path) -> None:
    for dirname in TYPE_TO_DIRNAME.values():
        (repo_root / dirname).mkdir(parents=True, exist_ok=True)


def _max_id_number(directory: Path, prefix: str) -> int:
    pattern = re.compile(rf"^{prefix}-(\d{{{ID_NUMBER_WIDTH}}})\.md$")
    highest = 0
    for path in directory.glob(f"{prefix}-*.md"):
        match = pattern.match(path.name)
        if not match:
            continue
        number = int(match.group(1))
        if number > highest:
            highest = number
    return highest


def next_record_id(repo_root: Path, record_type: RecordType) -> str:
    """Return the next sequential id for a type; numbering is per type."""
    prefix = TYPE_TO_PREFIX[record_type]
    directory = dir_for_type(repo_root, record_type)
    if not directory.exists():
        next_number = FIRST_ID_NUMBER
    else:
        next_number = _max_id_number(directory, prefix) + 1
    return f"{prefix}-{next_number:0{ID_NUMBER_WIDTH}d}"


# Template headings are part of the on-disk body contract: the extraction
# prompt instructs agents to fill them and the daemon parses them for gists.
DECISION_TEMPLATE = (
    "## Context / Problem\n\n"
    "## Decision\n\n"
    "## Rationale\n\n"
    "## Outcome / Learned\n\n"
    "## Source (transcript)\n"
)
LESSON_TEMPLATE = (
    "## What happened\n\n"
    "## Why\n\n"
    "## When discovered\n\n"
    "## General rule\n\n"
    "## Source (transcript)\n"
)


def decision_body_template() -> str:
    return DECISION_TEMPLATE


def lesson_body_template() -> str:
    return LESSON_TEMPLATE


@dataclass
class NewRecordSpec:
    project: str
    provenance: Provenance
    tags: list[str] = field(default_factory=list)
    salience: float = DEFAULT_SALIENCE
    date: datetime.date | None = None
    body: str | None = None


def _write_text_atomic(path: Path, text: str) -> None:
    # Write to a temp file in the same directory, then rename: readers never
    # observe a partially written record.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except OSError:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def read_record(path: Path) -> tuple[Record, str]:
    text = path.read_text(encoding="utf-8")
    return parse_document(text)


def _create_record(repo_root: Path, record_type: RecordType, spec: NewRecordSpec, body: str) -> Path:
    ensure_dirs(repo_root)
    record = Record(
        id=next_record_id(repo_root, record_type),
        type=record_type,
        status=RecordStatus.PROPOSED,
        date=spec.date or datetime.date.today(),
        project=spec.project,
        provenance=spec.provenance,
        tags=list(spec.tags),
        salience=spec.salience,
    )
    path = dir_for_type(repo_root, record_type) / f"{record.id}.md"
    _write_text_atomic(path, serialize_document(record, body))
    return path


def create_decision(repo_root: Path, spec: NewRecordSpec) -> Path:
    """Create a new decision record in `proposed` status and return its path."""
    body = spec.body or decision_body_template()
    return _create_record(repo_root, RecordType.DECISION, spec, body)


def create_lesson(repo_root: Path, spec: NewRecordSpec) -> Path:
    """Create a new lesson record in `proposed` status and return its path."""
    body = spec.body or lesson_body_template()
    return _create_record(repo_root, RecordType.LESSON, spec, body)


def find_record_path(repo_root: Path, record_id: str) -> Path:
    """Resolve a record id to its file path; the type is derived from the prefix."""
    if not ID_PATTERN.match(record_id):
        raise ValueError(f"invalid id format: {record_id}")
    prefix = record_id.split("-", 1)[0]
    record_type = PREFIX_TO_TYPE[prefix]
    path = dir_for_type(repo_root, record_type) / f"{record_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"record not found: {record_id}")
    return path


def read_record_by_id(repo_root: Path, record_id: str) -> tuple[Record, str]:
    return read_record(find_record_path(repo_root, record_id))


def update_status(repo_root: Path, record_id: str, new_status: RecordStatus) -> Path:
    path = find_record_path(repo_root, record_id)
    record, body = read_record(path)
    record.status = new_status
    _write_text_atomic(path, serialize_document(record, body))
    return path


LOCKED_STATUSES = frozenset(
    {RecordStatus.ACCEPTED, RecordStatus.SUPERSEDED, RecordStatus.REVERTED_AS_MISTAKE}
)


class ImmutableRecordError(Exception):
    pass


def write_body(repo_root: Path, record_id: str, new_body: str) -> Path:
    """Replace a record's body.

    Only allowed while the record is still `proposed`: accepted, superseded,
    and reverted records are immutable — revisions go through supersession.
    """
    path = find_record_path(repo_root, record_id)
    record, _ = read_record(path)
    if record.status in LOCKED_STATUSES:
        raise ImmutableRecordError(
            f"{record_id} has status '{record.status.value}' — body is immutable"
        )
    _write_text_atomic(path, serialize_document(record, new_body))
    return path


@dataclass
class SupersedeSpec:
    old_id: str
    new_spec: NewRecordSpec
    rationale: str


SUPERSESSION_RATIONALE_HEADING = "## Supersession rationale"


def _inject_rationale(body: str, rationale: str) -> str:
    return f"{body.rstrip()}\n\n{SUPERSESSION_RATIONALE_HEADING}\n{rationale.strip()}\n"


class SupersessionLinkError(ValueError):
    pass


@dataclass(frozen=True)
class SupersessionLinkResult:
    old_record: Record
    new_record: Record
    already_linked: bool


def link_supersession(repo_root: Path, old_id: str, new_id: str) -> SupersessionLinkResult:
    """Link two existing records so that `new_id` supersedes `old_id`.

    The link is always bidirectional (`supersedes` on the new record,
    `superseded-by` plus `superseded` status on the old one). Idempotent:
    relinking an already linked pair is a no-op, and a partial one-sided
    link is healed rather than rejected.
    """
    if old_id == new_id:
        raise SupersessionLinkError(f"a record cannot supersede itself: {old_id}")
    old_path = find_record_path(repo_root, old_id)
    new_path = find_record_path(repo_root, new_id)
    old_record, old_body = read_record(old_path)
    new_record, new_body = read_record(new_path)
    if new_id in old_record.superseded_by and old_id in new_record.supersedes:
        return SupersessionLinkResult(old_record, new_record, already_linked=True)
    if old_id in new_record.superseded_by:
        raise SupersessionLinkError(
            f"already linked in the reverse direction: {old_id} supersedes {new_id}"
        )
    if old_record.status is RecordStatus.REVERTED_AS_MISTAKE:
        raise SupersessionLinkError(
            f"{old_id} has status reverted-as-mistake — it cannot be superseded"
        )
    # Write the new record first: if we crash in between, lint flags the
    # dangling one-sided link and a retry heals it.
    if old_id not in new_record.supersedes:
        new_record.supersedes = [*new_record.supersedes, old_id]
    _write_text_atomic(new_path, serialize_document(new_record, new_body))
    old_record.status = RecordStatus.SUPERSEDED
    if new_id not in old_record.superseded_by:
        old_record.superseded_by = [*old_record.superseded_by, new_id]
    _write_text_atomic(old_path, serialize_document(old_record, old_body))
    return SupersessionLinkResult(old_record, new_record, already_linked=False)


def supersede(repo_root: Path, spec: SupersedeSpec) -> Path:
    """Create a replacement record for `spec.old_id` and link the pair.

    A non-empty rationale is mandatory; it is appended to the new record's
    body under a dedicated heading. Only the newest record in a supersession
    chain may be superseded.
    """
    if not spec.rationale or not spec.rationale.strip():
        raise ValueError("supersession requires a non-empty rationale")
    old_path = find_record_path(repo_root, spec.old_id)
    old_record, old_body = read_record(old_path)
    if old_record.status in (RecordStatus.SUPERSEDED, RecordStatus.REVERTED_AS_MISTAKE):
        raise ValueError(
            "a record that is already superseded/reverted cannot be superseded again; "
            "supersede the most recent record instead"
        )
    template = (
        decision_body_template()
        if old_record.type is RecordType.DECISION
        else lesson_body_template()
    )
    new_body = _inject_rationale(spec.new_spec.body or template, spec.rationale)
    new_path = _create_record(repo_root, old_record.type, spec.new_spec, new_body)
    new_record, _ = read_record(new_path)
    new_record.supersedes = [spec.old_id]
    _write_text_atomic(new_path, serialize_document(new_record, new_body))
    old_record.status = RecordStatus.SUPERSEDED
    old_record.superseded_by = [new_record.id]
    _write_text_atomic(old_path, serialize_document(old_record, old_body))
    return new_path
