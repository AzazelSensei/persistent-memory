import json
import textwrap

import pytest

from persistent_memory.daemon import services


def _line(**kw):
    return json.dumps(kw)


def _user(cwd, text, ts):
    return _line(type="user", cwd=cwd, timestamp=ts,
                 message={"role": "user", "content": text})


def _assistant(cwd, text, ts):
    return _line(type="assistant", cwd=cwd, timestamp=ts,
                 message={"role": "assistant", "content": [{"type": "text", "text": text}]})


def _write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def projects_root(tmp_path):
    root = tmp_path / "projects"
    alpha_cwd = "/Users/dev/Desktop/alpha"
    _write_jsonl(root / "-Users-dev-Desktop-alpha" / "s1.jsonl", [
        _user(alpha_cwd, "Postgres mi MySQL mi?", "2026-06-01T10:00:00.000Z"),
        _assistant(alpha_cwd, "Postgres oneririm.", "2026-06-01T10:00:05.000Z"),
    ])
    _write_jsonl(root / "-Users-dev-Desktop-alpha" / "s2.jsonl", [
        _user(alpha_cwd, "Timeout sorunu var", "2026-06-02T11:00:00.000Z"),
        _assistant(alpha_cwd, "Retry ekleyelim.", "2026-06-02T11:00:05.000Z"),
    ])
    beta_cwd = "/Users/dev/Desktop/beta"
    _write_jsonl(root / "-Users-dev-Desktop-beta" / "s3.jsonl", [
        _user(beta_cwd, "Playwright kuralim", "2026-06-03T12:00:00.000Z"),
        _assistant(beta_cwd, "Tamam.", "2026-06-03T12:00:05.000Z"),
    ])
    noise_cwd = "/private/tmp/junk"
    _write_jsonl(root / "-private-tmp-junk" / "n.jsonl", [
        _user(noise_cwd, "noise", "2026-06-09T00:00:00.000Z"),
    ])
    return root


def _write_record(directory, rec_id, rec_type, project, date="2026-06-01"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec_id}.md").write_text(
        textwrap.dedent(f"""\
            ---
            id: {rec_id}
            type: {rec_type}
            status: accepted
            date: {date}
            project: {project}
            salience: 0.5
            ---
            ## Govde
            x
            """),
        encoding="utf-8",
    )


def test_project_overview_lists_transcript_projects_ordered(projects_root, tmp_path):
    rows = services.project_overview(projects_root=projects_root, records_dir=tmp_path)
    assert [r["name"] for r in rows] == ["beta", "alpha"]
    alpha = next(r for r in rows if r["name"] == "alpha")
    assert alpha["transcript_count"] == 2
    assert alpha["last_activity"] == "2026-06-02T11:00:05.000Z"


def test_project_overview_excludes_noise(projects_root, tmp_path):
    rows = services.project_overview(projects_root=projects_root, records_dir=tmp_path)
    assert all(r["name"] != "junk" for r in rows)
    assert len(rows) == 2


def test_project_overview_counts_our_records(projects_root, tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision", "alpha")
    _write_record(tmp_path / "decisions", "D-0002", "decision", "beta")
    _write_record(tmp_path / "lessons", "L-0001", "lesson", "alpha")
    rows = services.project_overview(projects_root=projects_root, records_dir=tmp_path)
    alpha = next(r for r in rows if r["name"] == "alpha")
    assert alpha["decisions_count"] == 1
    assert alpha["lessons_count"] == 1
    beta = next(r for r in rows if r["name"] == "beta")
    assert beta["decisions_count"] == 1
    assert beta["lessons_count"] == 0


def test_project_overview_missing_root_returns_empty(tmp_path):
    rows = services.project_overview(projects_root=tmp_path / "nope", records_dir=tmp_path)
    assert rows == []


def test_project_detail_returns_recent_messages(projects_root, tmp_path):
    _write_record(tmp_path / "decisions", "D-0001", "decision", "alpha")
    detail = services.project_detail(project="alpha", projects_root=projects_root, records_dir=tmp_path)
    assert detail["name"] == "alpha"
    texts = [m["text"] for m in detail["recent_messages"]]
    assert "Postgres mi MySQL mi?" in texts
    assert "Retry ekleyelim." in texts
    assert [r["id"] for r in detail["decisions"]] == ["D-0001"]
    assert detail["lessons"] == []


def test_project_detail_recent_messages_most_recent_first(projects_root, tmp_path):
    detail = services.project_detail(project="alpha", projects_root=projects_root, records_dir=tmp_path)
    timestamps = [m["timestamp"] for m in detail["recent_messages"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_project_detail_unknown_project_graceful(projects_root, tmp_path):
    detail = services.project_detail(project="nonexistent", projects_root=projects_root, records_dir=tmp_path)
    assert detail["name"] == "nonexistent"
    assert detail["recent_messages"] == []
    assert detail["decisions"] == []


def test_project_detail_empty_project_guarded(projects_root, tmp_path):
    detail = services.project_detail(project="", projects_root=projects_root, records_dir=tmp_path)
    assert detail["recent_messages"] == []
