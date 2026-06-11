from persistent_memory.schema import RecordStatus, RecordType


def test_record_type_values():
    assert {t.value for t in RecordType} == {"decision", "lesson", "principle"}


def test_record_status_values():
    expected = {"proposed", "accepted", "superseded", "reverted-as-mistake"}
    assert {s.value for s in RecordStatus} == expected


def test_enum_is_str():
    assert RecordType.DECISION == "decision"
    assert RecordStatus.ACCEPTED == "accepted"
