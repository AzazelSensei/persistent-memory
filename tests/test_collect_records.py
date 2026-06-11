from pathlib import Path

from persistent_memory.lint import LoadedRecord, collect_records


def write_record(dir_path: Path, name: str, body: str) -> None:
    (dir_path / name).write_text(body, encoding="utf-8")


VALID_DECISION = """---
id: D-0001
type: decision
status: accepted
date: 2026-01-10
project: example-app
provenance: {session: s1, cwd: /tmp, agent: claude-opus-4-8}
tags: [veritabani]
supersedes: []
superseded-by: []
salience: 0.8
---
## Bağlam / Problem
ornek
## Karar
ornek
## Gerekçe
ornek
"""


def test_collect_records_loads_valid_markdown(tmp_path):
    write_record(tmp_path, "D-0001-ornek.md", VALID_DECISION)
    loaded = collect_records(tmp_path)
    assert len(loaded) == 1
    assert isinstance(loaded[0], LoadedRecord)
    assert loaded[0].record.id == "D-0001"
    assert loaded[0].path.name == "D-0001-ornek.md"


def test_collect_records_skips_index_md(tmp_path):
    write_record(tmp_path, "D-0001-ornek.md", VALID_DECISION)
    write_record(tmp_path, "index.md", "# katalog\n")
    loaded = collect_records(tmp_path)
    assert len(loaded) == 1


def test_collect_records_empty_dir_returns_empty(tmp_path):
    assert collect_records(tmp_path) == []
