from persistent_memory.records import decision_body_template, lesson_body_template


def test_decision_template_has_required_sections():
    body = decision_body_template()
    for heading in [
        "## Context / Problem",
        "## Decision",
        "## Rationale",
        "## Outcome / Learned",
        "## Source (transcript)",
    ]:
        assert heading in body


def test_lesson_template_has_required_sections():
    body = lesson_body_template()
    for heading in [
        "## What happened",
        "## Why",
        "## When discovered",
        "## General rule",
        "## Source (transcript)",
    ]:
        assert heading in body
