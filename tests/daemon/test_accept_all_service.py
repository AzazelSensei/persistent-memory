import textwrap

from persistent_memory.daemon import services


def write_record(directory, rec_id, rec_type, status, project="alpha"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec_id}.md").write_text(
        textwrap.dedent(f"""\
            ---
            id: {rec_id}
            type: {rec_type}
            status: {status}
            date: '2026-06-02'
            project: {project}
            provenance:
              session: s
              cwd: /tmp
              agent: a
            tags: []
            supersedes: []
            superseded-by: []
            salience: 0.5
            ---
            # Baslik {rec_id}

            ## Karar
            govde
            """),
        encoding="utf-8",
    )


def _status(directory, rec_id):
    from persistent_memory.records import read_record
    record, _ = read_record(directory / f"{rec_id}.md")
    return record.status.value


def test_accept_all_flips_only_proposed(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed")
    write_record(tmp_path / "decisions", "D-0002", "decision", "accepted")
    write_record(tmp_path / "lessons", "L-0001", "lesson", "proposed")
    count = services.accept_all(tmp_path)
    assert count == 2
    assert _status(tmp_path / "decisions", "D-0001") == "accepted"
    assert _status(tmp_path / "decisions", "D-0002") == "accepted"
    assert _status(tmp_path / "lessons", "L-0001") == "accepted"


def test_accept_all_filters_by_project(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed", project="alpha")
    write_record(tmp_path / "decisions", "D-0002", "decision", "proposed", project="beta")
    count = services.accept_all(tmp_path, project="alpha")
    assert count == 1
    assert _status(tmp_path / "decisions", "D-0001") == "accepted"
    assert _status(tmp_path / "decisions", "D-0002") == "proposed"


def test_accept_all_filters_by_type(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed")
    write_record(tmp_path / "lessons", "L-0001", "lesson", "proposed")
    count = services.accept_all(tmp_path, record_type="lesson")
    assert count == 1
    assert _status(tmp_path / "decisions", "D-0001") == "proposed"
    assert _status(tmp_path / "lessons", "L-0001") == "accepted"


def test_accept_all_returns_zero_when_none_match(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "accepted")
    assert services.accept_all(tmp_path) == 0


def test_list_records_with_titles_includes_title(tmp_path):
    write_record(tmp_path / "decisions", "D-0001", "decision", "proposed")
    rows = services.list_records_with_titles([tmp_path / "decisions"])
    assert rows[0]["id"] == "D-0001"
    assert rows[0]["title"] == "Baslik D-0001"
    assert rows[0]["status"] == "proposed"
