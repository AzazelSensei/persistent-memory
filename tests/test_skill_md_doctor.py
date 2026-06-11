from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parents[1] / "skill" / "SKILL.md"


def test_documents_doctor_command():
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "doctor" in body.lower()
    assert "persistent_memory.doctor" in body


def test_documents_check_and_full_auto():
    body = SKILL_PATH.read_text(encoding="utf-8")
    assert "--check" in body
    assert "install.sh" in body


def test_lists_managed_prerequisites():
    body = SKILL_PATH.read_text(encoding="utf-8").lower()
    for prereq in ("ollama", "bge-m3", "python3.12", "jq", "graphify"):
        assert prereq in body
