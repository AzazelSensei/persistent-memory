"""Corpus linter for memory records.

Runs consistency checks over a record directory: frontmatter schema,
duplicate ids, broken wikilinks, orphans, bidirectional supersession
integrity, staleness, and unknown frontmatter keys. Findings at WARNING
severity or above make the lint exit code non-zero.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import IntEnum
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import FRONTMATTER_DELIMITER, Record, RecordStatus, parse_document

INDEX_FILENAME = "index.md"
CHECK_SCHEMA = "schema"
CHECK_DUPLICATE_ID = "duplicate-id"
CHECK_BROKEN_LINK = "broken-link"
CHECK_ORPHAN = "orphan"
CHECK_SUPERSESSION = "supersession"
CHECK_STALENESS = "staleness"
CHECK_UNKNOWN_KEY = "unknown-key"
STALE_AFTER_DAYS = 180
LOW_SALIENCE = 0.3
SUPERSEDED_STATUSES = {RecordStatus.SUPERSEDED, RecordStatus.REVERTED_AS_MISTAKE}
FRONTMATTER_PARTS = 3


def _known_record_keys() -> set[str]:
    known: set[str] = set()
    for name, info in Record.model_fields.items():
        known.add(name)
        if info.alias:
            known.add(info.alias)
    return known


KNOWN_RECORD_KEYS = _known_record_keys()
WIKILINK_RE = re.compile(r"\[\[([DLP]-\d{4})\]\]")


class Severity(IntEnum):
    INFO = 1
    WARNING = 2
    ERROR = 3


FAILING_SEVERITY = Severity.WARNING


@dataclass(frozen=True)
class LintFinding:
    severity: Severity
    check: str
    record_id: str
    message: str


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.findings

    @property
    def exit_code(self) -> int:
        """1 if any finding is WARNING or worse; INFO findings alone pass."""
        if any(finding.severity >= FAILING_SEVERITY for finding in self.findings):
            return 1
        return 0

    def count(self, severity: Severity) -> int:
        return sum(1 for finding in self.findings if finding.severity is severity)


@dataclass(frozen=True)
class LoadedRecord:
    record: Record
    path: Path
    body: str


def collect_records(directory: Path) -> list[LoadedRecord]:
    """Load all parseable records from a directory, skipping index.md and
    malformed files (those are reported separately by check_schema)."""
    if not directory.is_dir():
        raise NotADirectoryError(f"corpus directory not found: {directory}")
    loaded: list[LoadedRecord] = []
    for md_path in sorted(directory.glob("*.md")):
        if md_path.name == INDEX_FILENAME:
            continue
        text = md_path.read_text(encoding="utf-8")
        try:
            record, body = parse_document(text)
        except (ValueError, ValidationError):
            continue
        loaded.append(LoadedRecord(record=record, path=md_path, body=body))
    return loaded


def check_schema(directory: Path) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for md_path in sorted(directory.glob("*.md")):
        if md_path.name == INDEX_FILENAME:
            continue
        text = md_path.read_text(encoding="utf-8")
        try:
            parse_document(text)
        except ValidationError as exc:
            findings.append(LintFinding(
                severity=Severity.ERROR,
                check=CHECK_SCHEMA,
                record_id=md_path.stem,
                message=f"invalid frontmatter schema: {exc.error_count()} error(s)",
            ))
        except ValueError as exc:
            findings.append(LintFinding(
                severity=Severity.ERROR,
                check=CHECK_SCHEMA,
                record_id=md_path.stem,
                message=f"failed to parse frontmatter: {exc}",
            ))
    return findings


def check_duplicate_id(loaded: list[LoadedRecord]) -> list[LintFinding]:
    counts = Counter(item.record.id for item in loaded)
    findings: list[LintFinding] = []
    for record_id, count in counts.items():
        if count <= 1:
            continue
        findings.append(LintFinding(
            severity=Severity.ERROR,
            check=CHECK_DUPLICATE_ID,
            record_id=record_id,
            message=f"id defined {count} times",
        ))
    return findings


def check_broken_links(loaded: list[LoadedRecord]) -> list[LintFinding]:
    known_ids = {item.record.id for item in loaded}
    findings: list[LintFinding] = []
    for item in loaded:
        targets = WIKILINK_RE.findall(item.body)
        missing = sorted({target for target in targets if target not in known_ids})
        for target in missing:
            findings.append(LintFinding(
                severity=Severity.ERROR,
                check=CHECK_BROKEN_LINK,
                record_id=item.record.id,
                message=f"broken wikilink: {target} not found",
            ))
    return findings


def _gather_referenced_ids(loaded: list[LoadedRecord]) -> set[str]:
    referenced: set[str] = set()
    for item in loaded:
        referenced.update(WIKILINK_RE.findall(item.body))
        referenced.update(item.record.supersedes)
        referenced.update(item.record.superseded_by)
    return referenced


def check_orphans(loaded: list[LoadedRecord]) -> list[LintFinding]:
    referenced = _gather_referenced_ids(loaded)
    findings: list[LintFinding] = []
    for item in loaded:
        if item.record.id in referenced:
            continue
        findings.append(LintFinding(
            severity=Severity.INFO,
            check=CHECK_ORPHAN,
            record_id=item.record.id,
            message="not referenced by any other record",
        ))
    return findings


def check_supersession(loaded: list[LoadedRecord]) -> list[LintFinding]:
    """Verify supersession links are bidirectional and statuses agree.

    Every `superseded-by` entry must be mirrored by `supersedes` on the
    target (and vice versa), and a record with `superseded-by` set must
    carry a superseded/reverted status.
    """
    by_id = {item.record.id: item.record for item in loaded}
    findings: list[LintFinding] = []
    for item in loaded:
        record = item.record
        for target_id in record.superseded_by:
            target = by_id.get(target_id)
            if target is None:
                findings.append(LintFinding(
                    Severity.ERROR, CHECK_SUPERSESSION, record.id,
                    f"superseded-by target missing: {target_id}",
                ))
                continue
            if record.id not in target.supersedes:
                findings.append(LintFinding(
                    Severity.ERROR, CHECK_SUPERSESSION, record.id,
                    f"bidirectional link inconsistent: {target_id}.supersedes "
                    f"does not contain {record.id}",
                ))
        if record.superseded_by and record.status not in SUPERSEDED_STATUSES:
            findings.append(LintFinding(
                Severity.WARNING, CHECK_SUPERSESSION, record.id,
                f"superseded-by is set but status={record.status.value}",
            ))
        for target_id in record.supersedes:
            target = by_id.get(target_id)
            if target is None:
                findings.append(LintFinding(
                    Severity.ERROR, CHECK_SUPERSESSION, record.id,
                    f"supersedes target missing: {target_id}",
                ))
                continue
            if record.id not in target.superseded_by:
                findings.append(LintFinding(
                    Severity.ERROR, CHECK_SUPERSESSION, record.id,
                    f"bidirectional link inconsistent: {target_id}.superseded-by "
                    f"does not contain {record.id}",
                ))
    deduped: list[LintFinding] = []
    for finding in findings:
        if finding not in deduped:
            deduped.append(finding)
    return deduped


def check_staleness(loaded: list[LoadedRecord], today: date) -> list[LintFinding]:
    """Flag records that are both old and low-salience; superseded ones are exempt."""
    cutoff = today - timedelta(days=STALE_AFTER_DAYS)
    findings: list[LintFinding] = []
    for item in loaded:
        record = item.record
        if record.status in SUPERSEDED_STATUSES:
            continue
        if record.date > cutoff:
            continue
        if record.salience >= LOW_SALIENCE:
            continue
        findings.append(LintFinding(
            Severity.WARNING, CHECK_STALENESS, record.id,
            f"stale: {record.date} (older than {STALE_AFTER_DAYS} days) and "
            f"salience {record.salience} < {LOW_SALIENCE}",
        ))
    return findings


def _frontmatter_map(text: str) -> dict | None:
    if not text.startswith(FRONTMATTER_DELIMITER):
        return None
    parts = text.split(FRONTMATTER_DELIMITER, 2)
    if len(parts) < FRONTMATTER_PARTS:
        return None
    try:
        raw = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def check_unknown_keys(directory: Path) -> list[LintFinding]:
    """Warn about frontmatter keys the schema would silently drop (e.g. typos)."""
    findings: list[LintFinding] = []
    for md_path in sorted(directory.glob("*.md")):
        if md_path.name == INDEX_FILENAME:
            continue
        text = md_path.read_text(encoding="utf-8")
        raw = _frontmatter_map(text)
        if raw is None:
            continue
        unknown = sorted(key for key in raw if key not in KNOWN_RECORD_KEYS)
        if not unknown:
            continue
        identifier = str(raw.get("id") or md_path.stem)
        findings.append(LintFinding(
            severity=Severity.WARNING,
            check=CHECK_UNKNOWN_KEY,
            record_id=identifier,
            message=f"unknown frontmatter key(s) (silently dropped): {', '.join(unknown)}",
        ))
    return findings


def _load_schema_valid(directory: Path) -> list[LoadedRecord]:
    # Unlike collect_records, this never raises on a missing directory:
    # run_lint must produce a report (possibly empty) instead of crashing.
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


def run_lint(directory: Path, today: date) -> LintReport:
    """Run every check over a record directory and aggregate the findings.

    Files that fail schema validation are reported once by check_schema and
    excluded from the remaining checks.
    """
    findings: list[LintFinding] = list(check_schema(directory))
    findings.extend(check_unknown_keys(directory))
    loaded = _load_schema_valid(directory)
    findings.extend(check_duplicate_id(loaded))
    findings.extend(check_broken_links(loaded))
    findings.extend(check_orphans(loaded))
    findings.extend(check_supersession(loaded))
    findings.extend(check_staleness(loaded, today=today))
    return LintReport(findings=findings)


EXIT_USAGE = 2


def _format_report_lines(report: LintReport) -> list[str]:
    if report.is_clean:
        return ["lint: clean, 0 findings"]
    lines = [
        f"lint: {len(report.findings)} finding(s) "
        f"(ERROR={report.count(Severity.ERROR)} "
        f"WARNING={report.count(Severity.WARNING)} "
        f"INFO={report.count(Severity.INFO)})",
    ]
    for finding in report.findings:
        lines.append(
            f"  [{finding.severity.name}] {finding.check} "
            f"{finding.record_id}: {finding.message}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m persistent_memory.lint <directory>", file=sys.stderr)
        return EXIT_USAGE
    report = run_lint(Path(args[0]), today=date.today())
    print("\n".join(_format_report_lines(report)))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
