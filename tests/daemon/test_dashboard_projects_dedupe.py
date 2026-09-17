"""Projects payload must expose one entry per project name (UI keys on id).

Record counts come from the already-loaded record list, not from a second
per-project corpus scan, so these tests drive both inputs: the transcript
project list and the records.
"""

from pathlib import Path

from persistent_memory.daemon import dashboard_data
from persistent_memory.transcripts import ProjectInfo


def _project_info(name, *, transcripts, last):
    return ProjectInfo(
        name=name,
        path=f"/tmp/{name}",
        dir=Path(f"/tmp/{name}"),
        transcript_count=transcripts,
        last_activity=last,
    )


def _record(project, kind="decision"):
    return {"project": project, "kind": kind}


def _patch_transcript_projects(monkeypatch, infos):
    monkeypatch.setattr(dashboard_data, "list_transcript_projects", lambda root: infos)


def _build(records, monkeypatch, infos):
    _patch_transcript_projects(monkeypatch, infos)
    return dashboard_data._build_projects(
        records, projects_root=Path("/tmp/projects"), records_dir=Path("/tmp/docs")
    )


def test_same_project_name_from_two_paths_collapses_to_one_entry(monkeypatch):
    projects = _build(
        [_record("bi"), _record("other")],
        monkeypatch,
        [
            _project_info("bi", transcripts=4, last="2026-07-20"),
            _project_info("bi", transcripts=7, last="2026-07-24"),
            _project_info("other", transcripts=1, last="2026-07-01"),
        ],
    )

    ids = [p["id"] for p in projects]
    assert ids == ["bi", "other"]
    assert len(ids) == len(set(ids))


def test_merged_entry_sums_transcripts_and_keeps_latest_activity(monkeypatch):
    projects = _build(
        [_record("bi")],
        monkeypatch,
        [
            _project_info("bi", transcripts=4, last="2026-07-20"),
            _project_info("bi", transcripts=7, last="2026-07-24"),
        ],
    )

    assert projects[0]["conv"] == 11
    assert projects[0]["last"] == "2026-07-24"


def test_counts_come_from_records_and_are_not_double_counted(monkeypatch):
    records = [_record("bi"), _record("bi"), _record("bi", kind="lesson")]
    projects = _build(
        records,
        monkeypatch,
        [
            _project_info("bi", transcripts=4, last="2026-07-20"),
            _project_info("bi", transcripts=7, last="2026-07-24"),
        ],
    )

    assert projects[0]["dec"] == 2
    assert projects[0]["les"] == 1


def test_project_with_records_but_no_transcripts_still_appears(monkeypatch):
    projects = _build(
        [_record("orphan"), _record("orphan", kind="lesson")],
        monkeypatch,
        [_project_info("other", transcripts=2, last="2026-07-01")],
    )

    orphan = next(p for p in projects if p["id"] == "orphan")
    assert orphan["dec"] == 1
    assert orphan["les"] == 1
    assert orphan["conv"] == 0


def test_project_with_transcripts_but_no_records_reports_zero_counts(monkeypatch):
    projects = _build(
        [],
        monkeypatch,
        [_project_info("empty", transcripts=3, last="2026-07-02")],
    )

    assert projects[0]["dec"] == 0
    assert projects[0]["les"] == 0
    assert projects[0]["conv"] == 3


def test_each_project_gets_a_colour(monkeypatch):
    projects = _build(
        [_record("bi"), _record("other")],
        monkeypatch,
        [
            _project_info("bi", transcripts=4, last="2026-07-20"),
            _project_info("other", transcripts=1, last="2026-07-01"),
        ],
    )

    assert all(p["color"] for p in projects)
