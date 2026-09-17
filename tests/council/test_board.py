import builtins
import json
import logging
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from persistent_memory.council.board import (
    MAX_READ_LIMIT,
    TAIL_READ_BYTES,
    _extract_last_valid_id,
    append_message,
    board_path,
    list_threads,
    read_messages,
)


def _council_dir(tmp_path):
    return tmp_path / "council"


def _fields(**overrides):
    fields = {
        "project": "alpha",
        "thread": "general",
        "author": "claude",
        "kind": "note",
        "body": "hello",
        "via": "mcp",
    }
    fields.update(overrides)
    return fields


def test_append_message_generates_sequential_ids(tmp_path):
    council_dir = _council_dir(tmp_path)
    first = append_message(council_dir, _fields(body="one"))
    second = append_message(council_dir, _fields(body="two"))
    third = append_message(council_dir, _fields(body="three"))

    assert first.id == "m-0001"
    assert second.id == "m-0002"
    assert third.id == "m-0003"


def test_append_message_ts_is_utc_and_z_suffixed(tmp_path):
    message = append_message(_council_dir(tmp_path), _fields())

    assert message.ts.endswith("Z")
    assert "+" not in message.ts
    assert message.ts.count(":") == 2


def test_read_messages_filters_by_thread(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(thread="general", body="g1"))
    append_message(council_dir, _fields(thread="c-0001", body="c1"))
    append_message(council_dir, _fields(thread="general", body="g2"))

    general_messages = read_messages(council_dir, "alpha", thread="general")
    council_messages = read_messages(council_dir, "alpha", thread="c-0001")

    assert [m.body for m in general_messages] == ["g1", "g2"]
    assert [m.body for m in council_messages] == ["c1"]


def test_read_messages_since_pages_forward_through_next_messages(tmp_path):
    council_dir = _council_dir(tmp_path)
    for i in range(5):
        append_message(council_dir, _fields(body=f"msg-{i}"))

    page = read_messages(council_dir, "alpha", since="m-0001", limit=2)

    assert [m.id for m in page] == ["m-0002", "m-0003"]


def test_read_messages_without_since_returns_newest_tail(tmp_path):
    council_dir = _council_dir(tmp_path)
    for i in range(5):
        append_message(council_dir, _fields(body=f"msg-{i}"))

    tail = read_messages(council_dir, "alpha", limit=2)

    assert [m.id for m in tail] == ["m-0004", "m-0005"]


def test_read_messages_since_invalid_id_raises_value_error(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="one"))

    with pytest.raises(ValueError):
        read_messages(council_dir, "alpha", since="zzz")


def test_read_messages_since_numeric_ordering_beyond_four_digits(tmp_path):
    council_dir = _council_dir(tmp_path)
    path = board_path(council_dir, "alpha")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for seq, body in ((9998, "a"), (9999, "b"), (10000, "c"), (10001, "d")):
        lines.append(
            json.dumps(
                {
                    "id": f"m-{seq}",
                    "ts": "2026-07-24T00:00:00Z",
                    "project": "alpha",
                    "thread": "general",
                    "author": "claude",
                    "kind": "note",
                    "body": body,
                    "via": "mcp",
                    "role": None,
                    "turn": None,
                    "refs": [],
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    later = read_messages(council_dir, "alpha", since="m-9999")

    assert [m.id for m in later] == ["m-10000", "m-10001"]


def test_read_messages_limit_is_clipped_to_max(tmp_path, monkeypatch):
    council_dir = _council_dir(tmp_path)
    monkeypatch.setattr("persistent_memory.council.board.MAX_READ_LIMIT", 3)
    for i in range(5):
        append_message(council_dir, _fields(body=f"msg-{i}"))

    result = read_messages(council_dir, "alpha", limit=1000)

    assert len(result) == 3


def test_read_messages_limit_zero_returns_empty(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="one"))

    assert read_messages(council_dir, "alpha", limit=0) == []


def test_read_messages_negative_limit_returns_empty(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="one"))

    assert read_messages(council_dir, "alpha", limit=-1) == []


def test_read_messages_skips_corrupt_lines(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="good-one"))
    path = board_path(council_dir, "alpha")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("not-json-at-all\n")
        handle.write(json.dumps({"id": "m-broken", "body": "missing fields"}) + "\n")
    append_message(council_dir, _fields(body="good-two"))

    result = read_messages(council_dir, "alpha")

    assert [m.body for m in result] == ["good-one", "good-two"]


def test_read_messages_returns_empty_list_when_missing(tmp_path):
    assert read_messages(_council_dir(tmp_path), "does-not-exist") == []


def test_read_messages_isolates_projects_sharing_a_slug(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(project="acme/api", body="from acme/api"))
    append_message(council_dir, _fields(project="acme-api", body="from acme-api"))

    first_project = read_messages(council_dir, "acme/api")
    second_project = read_messages(council_dir, "acme-api")

    assert [m.body for m in first_project] == ["from acme/api"]
    assert [m.body for m in second_project] == ["from acme-api"]


def test_list_threads_summarizes_each_thread(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(thread="general", author="claude", body="g1"))
    append_message(council_dir, _fields(thread="c-0001", author="codex", body="c1"))
    append_message(council_dir, _fields(thread="general", author="grok", body="g2"))

    threads = list_threads(council_dir, "alpha")
    by_name = {entry["thread"]: entry for entry in threads}

    assert by_name["general"]["count"] == 2
    assert set(by_name["general"]["authors"]) == {"claude", "grok"}
    assert by_name["c-0001"]["count"] == 1


def test_list_threads_isolates_projects_sharing_a_slug(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(project="acme/api", thread="general", body="a"))
    append_message(council_dir, _fields(project="acme-api", thread="general", body="b"))

    first_project_threads = list_threads(council_dir, "acme/api")
    second_project_threads = list_threads(council_dir, "acme-api")

    assert [t["count"] for t in first_project_threads] == [1]
    assert [t["count"] for t in second_project_threads] == [1]


def test_concurrent_appends_never_collide(tmp_path):
    council_dir = _council_dir(tmp_path)
    thread_count = 20
    threads = []

    def _append(index):
        append_message(council_dir, _fields(thread=f"c-{index:04d}", author="claude", body=f"body-{index}"))

    for i in range(thread_count):
        thread = threading.Thread(target=_append, args=(i,))
        threads.append(thread)

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    path = board_path(council_dir, "alpha")
    lines = [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    ids = [json.loads(line)["id"] for line in lines]

    assert len(lines) == thread_count
    assert len(set(ids)) == thread_count
    assert sorted(ids) == [f"m-{n:04d}" for n in range(1, thread_count + 1)]


def test_append_message_after_many_messages_produces_correct_id(tmp_path):
    council_dir = _council_dir(tmp_path)
    for i in range(200):
        append_message(council_dir, _fields(body=f"msg-{i}"))

    latest = append_message(council_dir, _fields(body="msg-200"))

    assert latest.id == "m-0201"


def test_append_message_id_monotonic_with_corrupt_trailing_line(tmp_path):
    council_dir = _council_dir(tmp_path)
    for i in range(10):
        append_message(council_dir, _fields(body=f"msg-{i}"))
    path = board_path(council_dir, "alpha")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("not-json-at-all\n")

    next_message = append_message(council_dir, _fields(body="after-corruption"))

    assert next_message.id == "m-0011"


def test_append_message_rejects_invalid_kind(tmp_path):
    with pytest.raises(ValidationError):
        append_message(_council_dir(tmp_path), _fields(kind="not-a-real-kind"))


def test_append_message_rejects_empty_body(tmp_path):
    with pytest.raises(ValidationError):
        append_message(_council_dir(tmp_path), _fields(body=""))


def test_append_message_rejects_oversized_body(tmp_path):
    with pytest.raises(ValidationError):
        append_message(_council_dir(tmp_path), _fields(body="x" * 32001))


def test_append_message_rejects_oversized_project(tmp_path):
    with pytest.raises(ValueError):
        append_message(_council_dir(tmp_path), _fields(project="p" * 121))


def test_append_message_rejects_too_many_refs(tmp_path):
    with pytest.raises(ValidationError):
        append_message(_council_dir(tmp_path), _fields(refs=[f"D-{i:04d}" for i in range(33)]))


def test_append_message_missing_project_raises_value_error(tmp_path):
    fields = _fields()
    del fields["project"]
    with pytest.raises(ValueError):
        append_message(_council_dir(tmp_path), fields)


def test_append_message_invalid_payload_does_not_create_directory(tmp_path):
    council_dir = _council_dir(tmp_path)
    with pytest.raises(ValidationError):
        append_message(council_dir, _fields(body=""))
    assert not council_dir.exists()


def test_append_message_invalid_kind_does_not_create_directory(tmp_path):
    council_dir = _council_dir(tmp_path)
    with pytest.raises(ValidationError):
        append_message(council_dir, _fields(kind="not-a-real-kind"))
    assert not council_dir.exists()


def test_append_message_rejects_empty_project(tmp_path):
    with pytest.raises(ValidationError):
        append_message(_council_dir(tmp_path), _fields(project=""))


def test_append_message_rejects_whitespace_only_project(tmp_path):
    with pytest.raises(ValidationError):
        append_message(_council_dir(tmp_path), _fields(project="   "))


def test_append_message_after_long_body_exceeding_tail_read_bytes(tmp_path):
    council_dir = _council_dir(tmp_path)
    first = append_message(council_dir, _fields(body="x" * 20000))

    second = append_message(council_dir, _fields(body="short-follow-up"))

    assert first.id == "m-0001"
    assert second.id == "m-0002"


def test_append_message_after_two_consecutive_long_bodies(tmp_path):
    council_dir = _council_dir(tmp_path)
    first = append_message(council_dir, _fields(body="x" * 20000))
    second = append_message(council_dir, _fields(body="y" * 20000))
    third = append_message(council_dir, _fields(body="short"))

    assert first.id == "m-0001"
    assert second.id == "m-0002"
    assert third.id == "m-0003"


def test_list_threads_secondary_sort_key_breaks_tie_on_same_timestamp(tmp_path, monkeypatch):
    council_dir = _council_dir(tmp_path)
    fixed_ts = "2026-07-24T12:00:00Z"
    monkeypatch.setattr("persistent_memory.council.board._current_timestamp", lambda: fixed_ts)

    append_message(council_dir, _fields(thread="thread-a", body="a1"))
    append_message(council_dir, _fields(thread="thread-b", body="b1"))

    threads = list_threads(council_dir, "alpha")

    assert threads[0]["thread"] == "thread-b"
    assert threads[0]["last_ts"] == fixed_ts
    assert threads[1]["thread"] == "thread-a"


def test_append_message_after_truncated_trailing_line_does_not_corrupt(tmp_path):
    council_dir = _council_dir(tmp_path)
    for i in range(3):
        append_message(council_dir, _fields(body=f"msg-{i}"))
    path = board_path(council_dir, "alpha")
    truncated = (
        '{"id": "m-0004", "ts": "2026-07-24T00:00:00Z", "project": "alpha", '
        '"thread": "general", "auth'
    )
    with open(path, "ab") as handle:
        handle.write(truncated.encode("utf-8"))

    new_message = append_message(council_dir, _fields(body="after-truncation"))

    raw_lines = path.read_text(encoding="utf-8").split("\n")
    assert truncated in raw_lines
    assert new_message.id not in ("m-0001", "m-0002", "m-0003")

    read_back = read_messages(council_dir, "alpha")
    bodies = [m.body for m in read_back]
    ids = [m.id for m in read_back]
    assert "after-truncation" in bodies
    assert len(ids) == len(set(ids))
    assert new_message.id == read_back[-1].id
    assert read_back[-1].body == "after-truncation"


def test_append_message_twice_after_truncated_trailing_line_no_duplicate_ids(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="first"))
    path = board_path(council_dir, "alpha")
    with open(path, "ab") as handle:
        handle.write(b'{"id": "m-0002", "body": "cut off, no newline')

    second = append_message(council_dir, _fields(body="second"))
    third = append_message(council_dir, _fields(body="third"))

    assert second.id != third.id
    assert third.id == f"m-{int(second.id.split('-')[1]) + 1:04d}"


# ---------------------------------------------------------------------------
# BUG 1 — tail-read must survive a cut landing mid multi-byte UTF-8 character
# ---------------------------------------------------------------------------


def test_extract_last_valid_id_survives_multibyte_char_cut_mid_character():
    line = b'{"id":"m-0001","body":"' + "ğüşiöç".encode("utf-8") * 3 + b'"}'
    cut = line[:-3]

    assert _extract_last_valid_id([cut]) is None


def test_append_message_after_large_turkish_board_does_not_crash(tmp_path):
    # Regression must actually stress the tail-read boundary: the final
    # board message before the next append is deliberately larger than
    # TAIL_READ_BYTES and made entirely of 2-byte Turkish characters, with a
    # pad byte chosen so the tail-read cut point lands mid-character (proven
    # by construction, not by chance) — see the sibling precision test
    # `test_append_message_survives_tail_boundary_splitting_a_multibyte_character`
    # for the same technique on a minimal file.
    council_dir = _council_dir(tmp_path)
    turkish_body = "Türkçe karakterli mesaj: ğüşiöçĞÜŞİÖÇ ışık düşünce köşe " * 20
    for i in range(30):
        append_message(council_dir, _fields(body=f"{turkish_body}-{i}"))

    path = board_path(council_dir, "alpha")
    base_size = path.stat().st_size

    char = "ğ".encode("utf-8")
    assert len(char) == 2
    repeats = TAIL_READ_BYTES + 500
    prefix = (
        '{"id":"m-0031","ts":"2026-07-24T00:00:01Z","project":"alpha","thread":"general",'
        '"author":"claude","kind":"note","body":"'
    ).encode("utf-8")
    suffix = '","via":"mcp","role":null,"turn":null,"refs":[]}\n'.encode("utf-8")

    chosen_pad = None
    for pad_len in (0, 1):
        pad = b"x" * pad_len
        body_bytes = char * repeats
        line = prefix + pad + body_bytes + suffix
        file_size = base_size + len(line)
        split_offset = file_size - TAIL_READ_BYTES
        body_region_start = base_size + len(prefix) + len(pad)
        k = split_offset - body_region_start
        if 0 < k < len(body_bytes) - 1 and k % 2 == 1:
            chosen_pad = pad
            break
    assert chosen_pad is not None, "could not construct a mid-character tail-read boundary"

    with open(path, "ab") as handle:
        handle.write(prefix + chosen_pad + (char * repeats) + suffix)

    assert path.stat().st_size > TAIL_READ_BYTES

    next_message = append_message(council_dir, _fields(body="son mesaj"))

    assert next_message.id == "m-0032"
    tail = read_messages(council_dir, "alpha", limit=1)
    assert tail[0].id == "m-0032"
    assert tail[0].body == "son mesaj"


def test_append_message_survives_tail_boundary_splitting_a_multibyte_character(tmp_path):
    council_dir = _council_dir(tmp_path)
    path = board_path(council_dir, "alpha")
    path.parent.mkdir(parents=True, exist_ok=True)

    seed_line = (
        json.dumps(
            {
                "id": "m-0001",
                "ts": "2026-07-24T00:00:00Z",
                "project": "alpha",
                "thread": "general",
                "author": "claude",
                "kind": "note",
                "body": "seed",
                "via": "mcp",
                "role": None,
                "turn": None,
                "refs": [],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    prefix = (
        '{"id":"m-0002","ts":"2026-07-24T00:00:01Z","project":"alpha","thread":"general",'
        '"author":"claude","kind":"note","body":"'
    ).encode("utf-8")
    suffix = '","via":"mcp","role":null,"turn":null,"refs":[]}\n'.encode("utf-8")

    char = "ğ".encode("utf-8")
    assert len(char) == 2
    repeats = TAIL_READ_BYTES
    body = char * repeats

    # Find a one-byte ascii pad (0 or 1 bytes) that makes the tail-read cut
    # point land exactly between the two bytes of one repeated character,
    # instead of on a character boundary.
    chosen_pad = None
    for pad_len in (0, 1):
        pad = b"x" * pad_len
        file_size = len(seed_line) + len(prefix) + len(pad) + len(body) + len(suffix)
        split_offset = file_size - TAIL_READ_BYTES
        body_region_start = len(seed_line) + len(prefix) + len(pad)
        k = split_offset - body_region_start
        if 0 < k < len(body) - 1 and k % 2 == 1:
            chosen_pad = pad
            break
    assert chosen_pad is not None, "could not construct a mid-character tail-read boundary"

    path.write_bytes(seed_line + prefix + chosen_pad + body + suffix)

    new_message = append_message(council_dir, _fields(body="after-boundary-cut"))

    assert new_message.id == "m-0003"


# ---------------------------------------------------------------------------
# MUST-FIX 1 — the read path (_read_all_messages) must decode line-by-line,
# not the whole file at once: a single invalid byte anywhere in the file
# must not kill every other message on the board.
# ---------------------------------------------------------------------------


def test_read_messages_survives_a_single_invalid_byte_mid_file(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="before-corruption"))
    append_message(council_dir, _fields(body="also-before-corruption"))
    append_message(council_dir, _fields(body="after-corruption"))

    path = board_path(council_dir, "alpha")
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    # Corrupt the middle message's line with a single invalid UTF-8 byte
    # (0xFF is never valid on its own in UTF-8).
    target_index = next(i for i, line in enumerate(lines) if b"also-before-corruption" in line)
    lines[target_index] = lines[target_index][:20] + b"\xff" + lines[target_index][20:]
    path.write_bytes(b"\n".join(lines))

    result = read_messages(council_dir, "alpha")

    assert [m.body for m in result] == ["before-corruption", "after-corruption"]


def test_list_threads_survives_a_single_invalid_byte_mid_file(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(thread="general", body="before-corruption"))
    append_message(council_dir, _fields(thread="general", body="also-before-corruption"))
    append_message(council_dir, _fields(thread="general", body="after-corruption"))

    path = board_path(council_dir, "alpha")
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    target_index = next(i for i, line in enumerate(lines) if b"also-before-corruption" in line)
    lines[target_index] = lines[target_index][:20] + b"\xff" + lines[target_index][20:]
    path.write_bytes(b"\n".join(lines))

    threads = list_threads(council_dir, "alpha")

    assert threads[0]["thread"] == "general"
    assert threads[0]["count"] == 2


def test_append_message_still_works_after_an_earlier_invalid_byte_corrupted_the_board(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="one"))
    append_message(council_dir, _fields(body="two"))
    append_message(council_dir, _fields(body="three"))

    path = board_path(council_dir, "alpha")
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    # Corrupt the MIDDLE message, not the tail one, so the tail-read id
    # lookup (which only needs the last valid line) is unaffected — this
    # isolates the read-path (_read_all_messages) fix from the already-fixed
    # write-path (_last_message_id) tail-read logic.
    target_index = next(i for i, line in enumerate(lines) if b'"two"' in line)
    lines[target_index] = lines[target_index][:20] + b"\xff" + lines[target_index][20:]
    path.write_bytes(b"\n".join(lines))

    fourth = append_message(council_dir, _fields(body="four"))

    assert fourth.id == "m-0004"
    result = read_messages(council_dir, "alpha")
    assert [m.body for m in result] == ["one", "three", "four"]


def test_read_messages_fully_corrupt_file_returns_empty_list_without_raising(tmp_path):
    council_dir = _council_dir(tmp_path)
    path = board_path(council_dir, "alpha")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00garbage\xff\xff\xffnot json at all\xff\n\xff\xff")

    assert read_messages(council_dir, "alpha") == []
    assert list_threads(council_dir, "alpha") == []


def test_read_messages_logs_a_warning_when_skipping_a_corrupt_line(tmp_path, caplog):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="good"))
    path = board_path(council_dir, "alpha")
    with open(path, "ab") as handle:
        handle.write(b"\xff not valid utf-8 at all\n")

    with caplog.at_level(logging.WARNING, logger="persistent_memory.council.board"):
        result = read_messages(council_dir, "alpha")

    assert [m.body for m in result] == ["good"]
    assert any("corrupt" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Faz 4c — read_messages() sondan-geriye tail-okuma optimizasyonu: since ile
# cursor'a ulasinca, since'siz limit ile yeterli mesaj toplayinca DURMALI;
# tum dosyayi okumamali. Bayt sayisi enstrumante edilerek kanitlanir.
# ---------------------------------------------------------------------------


def _instrument_bytes_read(monkeypatch):
    """Count every byte read through either `builtins.open` or
    `Path.read_bytes()`.

    Pathlib's `Path.open`/`Path.read_bytes` call `io.open` directly rather
    than looking up the `open` name at call time, so patching only
    `builtins.open` leaves a full-file read done via `path.read_bytes()`
    invisible to the counter (see MINOR 8). Both are patched so the "reads
    far fewer bytes than the full file" assertions actually measure the
    real I/O regardless of which mechanism the code path takes.
    """
    counter = {"total": 0}
    real_open = builtins.open
    real_read_bytes = Path.read_bytes

    def counting_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        original_read = handle.read

        def counted_read(*a, **kw):
            data = original_read(*a, **kw)
            counter["total"] += len(data)
            return data

        handle.read = counted_read
        return handle

    def counting_read_bytes(self, *args, **kwargs):
        data = real_read_bytes(self, *args, **kwargs)
        counter["total"] += len(data)
        return data

    monkeypatch.setattr(builtins, "open", counting_open)
    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)
    return counter


def _build_large_board(council_dir, count, thread_cycle=("general",)):
    for i in range(count):
        thread = thread_cycle[i % len(thread_cycle)]
        append_message(council_dir, _fields(thread=thread, body=f"msg-{i}-" + ("dolgu-metni " * 40)))


def test_read_messages_since_near_tail_reads_far_fewer_bytes_than_full_file(tmp_path, monkeypatch):
    council_dir = _council_dir(tmp_path)
    message_count = 600
    _build_large_board(council_dir, message_count)
    path = board_path(council_dir, "alpha")
    file_size = path.stat().st_size
    assert file_size > TAIL_READ_BYTES * 10

    last_id = f"m-{message_count:04d}"
    counter = _instrument_bytes_read(monkeypatch)

    result = read_messages(council_dir, "alpha", since=last_id, limit=50)

    assert result == []
    assert counter["total"] > 0
    assert counter["total"] < file_size // 5


def test_read_messages_tail_limit_reads_far_fewer_bytes_than_full_file(tmp_path, monkeypatch):
    council_dir = _council_dir(tmp_path)
    message_count = 600
    _build_large_board(council_dir, message_count)
    path = board_path(council_dir, "alpha")
    file_size = path.stat().st_size
    assert file_size > TAIL_READ_BYTES * 10

    counter = _instrument_bytes_read(monkeypatch)

    result = read_messages(council_dir, "alpha", limit=50)

    assert [m.id for m in result] == [f"m-{n:04d}" for n in range(message_count - 49, message_count + 1)]
    assert counter["total"] > 0
    assert counter["total"] < file_size // 5


def test_read_messages_since_stops_scanning_past_cursor_reads_bounded_bytes_regardless_of_board_size(
    tmp_path, monkeypatch
):
    council_dir = _council_dir(tmp_path)
    small_count = 300
    large_count = 3000
    small_dir = tmp_path / "small-council"
    large_dir = tmp_path / "large-council"
    _build_large_board(small_dir, small_count)
    _build_large_board(large_dir, large_count)

    small_counter = _instrument_bytes_read(monkeypatch)
    read_messages(small_dir, "alpha", since=f"m-{small_count - 1:04d}", limit=50)
    small_bytes = small_counter["total"]

    large_counter = _instrument_bytes_read(monkeypatch)
    read_messages(large_dir, "alpha", since=f"m-{large_count - 1:04d}", limit=50)
    large_bytes = large_counter["total"]

    assert large_bytes < small_bytes * 3


def test_read_messages_since_skips_corrupt_line_between_cursor_and_tail(tmp_path):
    council_dir = _council_dir(tmp_path)
    _build_large_board(council_dir, 300)
    path = board_path(council_dir, "alpha")
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    target_index = next(i for i, line in enumerate(lines) if b'"msg-298-' in line)
    lines[target_index] = lines[target_index][:20] + b"\xff" + lines[target_index][20:]
    path.write_bytes(b"\n".join(lines))

    result = read_messages(council_dir, "alpha", since="m-0295", limit=50)

    ids = [m.id for m in result]
    assert "m-0299" not in ids
    assert ids == ["m-0296", "m-0297", "m-0298", "m-0300"]


def test_read_messages_since_with_thread_filter_on_large_board(tmp_path):
    council_dir = _council_dir(tmp_path)
    _build_large_board(council_dir, 400, thread_cycle=("general", "c-0001"))

    result = read_messages(council_dir, "alpha", thread="c-0001", since="m-0390", limit=50)

    assert all(m.thread == "c-0001" for m in result)
    assert [m.id for m in result] == ["m-0392", "m-0394", "m-0396", "m-0398", "m-0400"]


# ---------------------------------------------------------------------------
# MINOR 8 — the byte counter must also see `Path.read_bytes()`, not just
# `builtins.open`. Pathlib's `Path.open`/`Path.read_bytes` call `io.open`
# directly rather than looking up the `open` name at call time, so patching
# only `builtins.open` leaves a full-file read via `Path.read_bytes()`
# invisible to the counter — a regression back to `_read_all_messages()`
# would silently keep the "few bytes read" assertions green.
# ---------------------------------------------------------------------------


def test_byte_instrumentation_counts_bytes_read_via_path_read_bytes(tmp_path, monkeypatch):
    council_dir = _council_dir(tmp_path)
    _build_large_board(council_dir, 50)
    path = board_path(council_dir, "alpha")

    counter = _instrument_bytes_read(monkeypatch)
    data = path.read_bytes()

    assert counter["total"] == len(data)


def test_byte_instrumentation_catches_a_regression_to_full_file_read(tmp_path, monkeypatch):
    from persistent_memory.council import board as board_module

    council_dir = _council_dir(tmp_path)
    message_count = 600
    _build_large_board(council_dir, message_count)
    path = board_path(council_dir, "alpha")
    file_size = path.stat().st_size
    assert file_size > TAIL_READ_BYTES * 10

    def _full_file_read_regression(_path, _project, _thread, _since_seq, _limit):
        # Emulates the old, pre-optimization implementation: decode the
        # whole file (via Path.read_bytes()) instead of tailing it.
        return board_module._read_all_messages(_path)

    monkeypatch.setattr(board_module, "_read_messages_backward", _full_file_read_regression)
    counter = _instrument_bytes_read(monkeypatch)

    board_module.read_messages(council_dir, "alpha", limit=50)

    # If this assertion fails, the byte counter is blind to whichever read
    # path the code actually took (see MINOR 8 above) and the "reads far
    # fewer bytes than the full file" tests elsewhere in this module cannot
    # be trusted to catch a regression back to a full-file read.
    assert counter["total"] >= file_size


def test_read_messages_handles_unterminated_final_line_without_crashing(tmp_path):
    council_dir = _council_dir(tmp_path)
    append_message(council_dir, _fields(body="first"))
    append_message(council_dir, _fields(body="second"))
    path = board_path(council_dir, "alpha")
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    path.write_bytes(raw[:-1])

    result = read_messages(council_dir, "alpha")

    assert [m.body for m in result] == ["first", "second"]
