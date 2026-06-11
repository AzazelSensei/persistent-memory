from pathlib import Path

from persistent_memory.index import _extract_title, format_index_row
from persistent_memory.lint import LoadedRecord
from persistent_memory.schema import parse_document
from tests.test_collect_records import VALID_DECISION


def loaded(text, name="D-0001-ornek-karar.md"):
    record, body = parse_document(text)
    return LoadedRecord(record=record, path=Path(name), body=body)


def test_row_contains_id_status_and_date():
    row = format_index_row(loaded(VALID_DECISION))
    assert "D-0001" in row
    assert "accepted" in row
    assert "2026-01-10" in row


def test_row_uses_first_heading_as_title():
    text = VALID_DECISION.replace("## Bağlam / Problem\nornek", "## Veritabanı seçimi\nornek")
    row = format_index_row(loaded(text))
    assert "Veritabanı seçimi" in row


def test_extract_title_prefers_h1_over_following_h2():
    text = VALID_DECISION.replace(
        "## Bağlam / Problem\nornek",
        "# Playwright scraper setup\n\n## Bağlam / Problem\nornek",
    )
    assert _extract_title(loaded(text)) == "Playwright scraper setup"


def test_row_uses_h1_title_not_first_section_heading():
    text = VALID_DECISION.replace(
        "## Bağlam / Problem\nornek",
        "# Playwright scraper setup\n\n## Bağlam / Problem\nornek",
    )
    row = format_index_row(loaded(text))
    assert "Playwright scraper setup" in row
    assert "Bağlam / Problem" not in row


def test_extract_title_falls_back_to_stem_when_no_heading():
    front_matter = VALID_DECISION.split("---\n")[1]
    text = f"---\n{front_matter}---\nduz metin govde, hic baslik yok\n"
    assert _extract_title(loaded(text)) == "D-0001-ornek-karar"


def test_superseded_by_is_shown_in_row():
    text = (VALID_DECISION
            .replace("status: accepted", "status: superseded")
            .replace("superseded-by: []", "superseded-by: [D-0002]"))
    row = format_index_row(loaded(text))
    assert "D-0002" in row
