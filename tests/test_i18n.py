from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

import persistent_memory.i18n as i18n
from persistent_memory.i18n import MESSAGES, reset_lang_cache, resolve_lang, t

TR_RECALL_HEADER = "## Hatırlatma — geçmiş kararlar ve dersler"
TR_PROMPT_RECALL_HEADER = (
    "📌 İlgili geçmiş hafıza (bu mesajla bağlantılı olabilecek geçmiş kararlar/dersler — "
    "alakalıysa dikkate al):"
)
TR_DOCTOR_HINT = "`/persistent-memory doctor` komutunu çalıştır"


@pytest.fixture
def clean_lang_env(monkeypatch):
    for var in ("PM_LANG", "LC_ALL", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_read_apple_locale", lambda: None)
    reset_lang_cache()
    yield monkeypatch
    reset_lang_cache()


def _use_lang(monkeypatch, lang: str):
    monkeypatch.setenv("PM_LANG", lang)
    reset_lang_cache()


def test_pm_lang_beats_lang(clean_lang_env):
    clean_lang_env.setenv("PM_LANG", "tr")
    clean_lang_env.setenv("LANG", "en_US.UTF-8")
    assert resolve_lang() == "tr"


def test_lang_locale_string_is_parsed(clean_lang_env):
    clean_lang_env.setenv("LANG", "tr_TR.UTF-8")
    assert resolve_lang() == "tr"


def test_lc_all_beats_lang(clean_lang_env):
    clean_lang_env.setenv("LC_ALL", "tr_TR")
    clean_lang_env.setenv("LANG", "en_US.UTF-8")
    assert resolve_lang() == "tr"


def test_unsupported_lang_falls_back_to_english(clean_lang_env):
    clean_lang_env.setenv("PM_LANG", "fr")
    assert resolve_lang() == "en"


def test_default_is_english_when_nothing_set(clean_lang_env):
    assert resolve_lang() == "en"


def test_apple_locale_used_when_env_empty(clean_lang_env):
    clean_lang_env.setattr(i18n, "_read_apple_locale", lambda: "tr_TR")
    reset_lang_cache()
    assert resolve_lang() == "tr"


def test_resolution_is_cached_until_reset(clean_lang_env):
    clean_lang_env.setenv("PM_LANG", "tr")
    assert resolve_lang() == "tr"
    clean_lang_env.setenv("PM_LANG", "en")
    assert resolve_lang() == "tr"
    reset_lang_cache()
    assert resolve_lang() == "en"


def test_t_falls_back_to_english_for_missing_translation(clean_lang_env):
    clean_lang_env.setitem(i18n.MESSAGES, "test.only_english", {"en": "hello"})
    _use_lang(clean_lang_env, "tr")
    assert t("test.only_english") == "hello"


def test_t_unknown_key_raises(clean_lang_env):
    with pytest.raises(KeyError):
        t("no.such.key")


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_catalog_has_english_and_turkish(key):
    entry = MESSAGES[key]
    assert set(entry) == {"en", "tr"}
    assert entry["en"].strip()
    assert entry["tr"].strip()


@dataclass
class _Record:
    id: str
    title: str
    body: str
    type: str = "decision"
    status: str = "accepted"
    date: str = "2026-06-01"
    project: str = "project-alpha"
    tags: list[str] = field(default_factory=list)
    salience: float = 0.8
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)


def test_recall_block_header_in_turkish(clean_lang_env):
    from persistent_memory.recall import build_recall_block
    from persistent_memory.retriever import RetrievalCandidate

    _use_lang(clean_lang_env, "tr")
    record = _Record(id="D-1", title="postgresql index", body="sorgu hizlandi")
    cands = [RetrievalCandidate(record=record, score=0.9)]
    block = build_recall_block(project="project-alpha", searcher=lambda **kwargs: cands)
    assert block.splitlines()[0] == TR_RECALL_HEADER


def test_prompt_recall_header_in_turkish(clean_lang_env):
    from persistent_memory.daemon.services import _format_prompt_recall_block

    _use_lang(clean_lang_env, "tr")
    view = SimpleNamespace(
        id="D-0001", title="batch fetch", project="alpha",
        body="## Decision\nsingle JOIN\n",
    )
    block = _format_prompt_recall_block([SimpleNamespace(record=view)], budget=700)
    assert block.splitlines()[0] == TR_PROMPT_RECALL_HEADER


def test_session_start_warning_in_turkish(clean_lang_env):
    from persistent_memory.hooks import session_start as ss

    _use_lang(clean_lang_env, "tr")
    clean_lang_env.setattr(ss, "detect_missing_critical", lambda: ["ollama-server"])
    warning = ss._build_warning()
    assert warning.startswith("⚠️ persistent-memory:")
    assert "ollama sunucusu kapalı" in warning
    assert TR_DOCTOR_HINT in warning
