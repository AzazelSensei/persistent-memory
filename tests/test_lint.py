from persistent_memory.lint import LintFinding, LintReport, Severity


def test_lint_finding_holds_severity_record_id_and_message():
    finding = LintFinding(
        severity=Severity.ERROR,
        check="duplicate-id",
        record_id="D-0007",
        message="duplicate id",
    )
    assert finding.severity is Severity.ERROR
    assert finding.record_id == "D-0007"


def test_empty_report_is_clean_and_exit_zero():
    report = LintReport(findings=[])
    assert report.is_clean is True
    assert report.exit_code == 0


def test_report_with_warning_only_exits_one():
    report = LintReport(findings=[
        LintFinding(Severity.WARNING, "staleness", "L-0003", "stale"),
    ])
    assert report.is_clean is False
    assert report.exit_code == 1


def test_report_with_info_only_exits_zero_but_not_clean():
    report = LintReport(findings=[
        LintFinding(Severity.INFO, "orphan", "D-0001", "orphan"),
    ])
    assert report.exit_code == 0
    assert report.is_clean is False


def test_report_with_error_exits_one_and_counts_by_severity():
    report = LintReport(findings=[
        LintFinding(Severity.INFO, "orphan", "D-0001", "orphan"),
        LintFinding(Severity.ERROR, "broken-link", "L-0002", "broken"),
    ])
    assert report.exit_code == 1
    assert report.count(Severity.ERROR) == 1
    assert report.count(Severity.INFO) == 1
