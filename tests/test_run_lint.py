from datetime import date

from persistent_memory.lint import LintReport, Severity, run_lint
from tests.test_collect_records import VALID_DECISION, write_record

TODAY = date(2026, 6, 2)


def test_clean_corpus_returns_clean_report(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    write_record(tmp_path, "l.md", VALID_DECISION.replace("D-0001", "D-0002") + "\n[[D-0001]]\n")
    report = run_lint(tmp_path, today=TODAY)
    assert isinstance(report, LintReport)
    assert report.count(Severity.ERROR) == 0
    assert report.count(Severity.WARNING) == 0


def test_broken_corpus_aggregates_findings_and_exits_one(tmp_path):
    write_record(tmp_path, "a.md", VALID_DECISION)
    write_record(tmp_path, "b.md", VALID_DECISION)
    write_record(tmp_path, "bad.md", VALID_DECISION.replace("status: accepted", "status: xx"))
    report = run_lint(tmp_path, today=TODAY)
    assert report.exit_code == 1
    assert report.count(Severity.ERROR) >= 2
    checks = {f.check for f in report.findings}
    assert "schema" in checks
    assert "duplicate-id" in checks


def test_schema_broken_file_excluded_from_other_checks(tmp_path):
    write_record(tmp_path, "bad.md", VALID_DECISION.replace("status: accepted", "status: xx"))
    report = run_lint(tmp_path, today=TODAY)
    assert report.count(Severity.ERROR) == 1
    assert report.findings[0].check == "schema"
