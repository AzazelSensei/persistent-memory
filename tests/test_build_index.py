from persistent_memory.index import build_index_markdown
from tests.test_collect_records import VALID_DECISION, write_record

LESSON = (VALID_DECISION
          .replace("id: D-0001", "id: L-0001")
          .replace("type: decision", "type: lesson")
          .replace("date: 2026-01-10", "date: 2026-03-01"))


def test_empty_corpus_produces_skeleton(tmp_path):
    md = build_index_markdown(tmp_path)
    assert "# Decision / Lesson Catalog" in md
    assert "## Decisions" in md
    assert "## Lessons" in md


def test_index_lists_records_under_correct_sections(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    write_record(tmp_path, "l.md", LESSON)
    md = build_index_markdown(tmp_path)
    decisions_section = md.split("## Lessons")[0]
    lessons_section = md.split("## Lessons")[1]
    assert "D-0001" in decisions_section
    assert "L-0001" in lessons_section


def test_decisions_sorted_by_date_descending(tmp_path):
    write_record(tmp_path, "old.md", VALID_DECISION)
    write_record(tmp_path, "new.md",
                 VALID_DECISION.replace("id: D-0001", "id: D-0002").replace("date: 2026-01-10", "date: 2026-05-01"))
    md = build_index_markdown(tmp_path)
    assert md.index("D-0002") < md.index("D-0001")


def test_header_shows_total_count(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    md = build_index_markdown(tmp_path)
    assert "Total: 1" in md


def test_malformed_record_is_skipped_without_raising(tmp_path):
    write_record(tmp_path, "d.md", VALID_DECISION)
    write_record(tmp_path, "broken.md", "no frontmatter, just plain text\n")
    md = build_index_markdown(tmp_path)
    assert "D-0001" in md
    assert "Total: 1" in md
