"""User-language layer: message catalog plus language resolution.

Resolution order is PM_LANG > LC_ALL > LANG > macOS AppleLocale > English.
Locale strings are normalized to their primary subtag ("tr_TR.UTF-8" ->
"tr"); values outside ``SUPPORTED_LANGS`` are skipped so an unsupported
setting degrades to English instead of breaking output. The resolved
language and the AppleLocale subprocess result are cached per process;
``reset_lang_cache`` exists for tests. ``t`` falls back to English when a
translation is missing but raises ``KeyError`` for unknown message ids so
catalog bugs fail loudly in tests rather than shipping silent English.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "tr")
LANG_ENV_VARS = ("PM_LANG", "LC_ALL", "LANG")
APPLE_LOCALE_CMD = ("defaults", "read", "-g", "AppleLocale")
APPLE_LOCALE_TIMEOUT_SECONDS = 2.0
LOCALE_SUBTAG_SEPARATORS = re.compile(r"[._@-]")

MESSAGES: dict[str, dict[str, str]] = {
    "recall.header": {
        "en": "## Recall — past decisions and lessons",
        "tr": "## Hatırlatma — geçmiş kararlar ve dersler",
    },
    "prompt_recall.header": {
        "en": (
            "📌 Relevant past memory (decisions/lessons that may relate to this message — "
            "consider if applicable):"
        ),
        "tr": (
            "📌 İlgili geçmiş hafıza (bu mesajla bağlantılı olabilecek geçmiş kararlar/dersler — "
            "alakalıysa dikkate al):"
        ),
    },
    "session_start.critical.ollama_server": {
        "en": "ollama server is down",
        "tr": "ollama sunucusu kapalı",
    },
    "session_start.critical.bge_m3": {
        "en": "bge-m3 model is missing",
        "tr": "bge-m3 modeli eksik",
    },
    "session_start.critical.venv": {
        "en": ".venv is not ready",
        "tr": ".venv hazır değil",
    },
    "session_start.doctor_hint": {
        "en": "run `/persistent-memory doctor`",
        "tr": "`/persistent-memory doctor` komutunu çalıştır",
    },
    "index.title": {
        "en": "# Decision / Lesson Catalog",
        "tr": "# Karar / Ders Kataloğu",
    },
    "index.empty_section": {
        "en": "_no records_",
        "tr": "_kayıt yok_",
    },
    "index.section.decisions": {
        "en": "## Decisions",
        "tr": "## Kararlar",
    },
    "index.section.lessons": {
        "en": "## Lessons",
        "tr": "## Dersler",
    },
    "index.section.principles": {
        "en": "## Principles",
        "tr": "## İlkeler",
    },
    "index.total": {
        "en": "_Total: {count} records_",
        "tr": "_Toplam: {count} kayıt_",
    },
    "dashboard.heading.decisions": {
        "en": "Decisions",
        "tr": "Kararlar",
    },
    "dashboard.heading.lessons": {
        "en": "Lessons",
        "tr": "Dersler",
    },
    # UI chrome — app shell (nav, KPIs, tweaks)
    "ui.nav.sec.review": {
        "en": "Review",
        "tr": "İnceleme",
    },
    "ui.nav.sec.explore": {
        "en": "Explore",
        "tr": "Keşfet",
    },
    "ui.nav.sec.tools": {
        "en": "Tools",
        "tr": "Araçlar",
    },
    "ui.nav.overview": {
        "en": "Overview",
        "tr": "Genel Bakış",
    },
    "ui.nav.decisions": {
        "en": "Decisions",
        "tr": "Kararlar",
    },
    "ui.nav.lessons": {
        "en": "Lessons",
        "tr": "Dersler",
    },
    "ui.nav.graph": {
        "en": "Graph",
        "tr": "Graf",
    },
    "ui.nav.projects": {
        "en": "Projects",
        "tr": "Projeler",
    },
    "ui.nav.timeline": {
        "en": "Timeline",
        "tr": "Zaman Çizelgesi",
    },
    "ui.nav.search": {
        "en": "Search",
        "tr": "Arama",
    },
    "ui.nav.health": {
        "en": "Health & audit",
        "tr": "Sağlık & denetim",
    },
    "ui.nav.supersession": {
        "en": "Supersession",
        "tr": "Yenileme",
    },
    "ui.nav.review_queue": {
        "en": "Review queue",
        "tr": "İnceleme kuyruğu",
    },
    "ui.search.placeholder": {
        "en": "Search memory — TR / EN…",
        "tr": "Hafızada ara — TR / EN…",
    },
    "ui.kpi.total_memories": {
        "en": "total memories",
        "tr": "toplam hafıza",
    },
    "ui.kpi.pending_review": {
        "en": "pending review",
        "tr": "bekleyen inceleme",
    },
    "ui.kpi.graph_edges": {
        "en": "graph edges",
        "tr": "graf kenarları",
    },
    "ui.tweaks.theme": {
        "en": "Theme",
        "tr": "Tema",
    },
    "ui.tweaks.dark_theme": {
        "en": "Dark theme",
        "tr": "Koyu tema",
    },
    "ui.tweaks.accent_color": {
        "en": "Accent color",
        "tr": "Vurgu rengi",
    },
    "ui.tweaks.layout": {
        "en": "Layout",
        "tr": "Yerleşim",
    },
    "ui.tweaks.density": {
        "en": "Density",
        "tr": "Yoğunluk",
    },
    "ui.tweaks.corners": {
        "en": "Corners",
        "tr": "Köşeler",
    },
    "ui.tweaks.typography": {
        "en": "Typography",
        "tr": "Tipografi",
    },
    "ui.tweaks.ui_font": {
        "en": "UI font",
        "tr": "Arayüz fontu",
    },
    # UI chrome — dashboard
    "ui.dash.heading": {
        "en": "Memory — overview",
        "tr": "Hafıza — genel bakış",
    },
    "ui.dash.total_memories": {
        "en": "Total memories",
        "tr": "Toplam hafıza",
    },
    "ui.dash.pending_review": {
        "en": "Pending review",
        "tr": "Bekleyen inceleme",
    },
    "ui.dash.graph_edges": {
        "en": "Graph edges",
        "tr": "Graf kenarları",
    },
    "ui.dash.projects": {
        "en": "Projects",
        "tr": "Projeler",
    },
    "ui.dash.records_pending": {
        "en": "records pending review",
        "tr": "inceleme bekleyen kayıt",
    },
    "ui.btn.enter_queue": {
        "en": "Enter queue",
        "tr": "Kuyruğa gir",
    },
    "ui.btn.view_list": {
        "en": "View list",
        "tr": "Listeyi gör",
    },
    "ui.dash.recent_activity": {
        "en": "Recent activity",
        "tr": "Son aktivite",
    },
    "ui.dash.health_audit": {
        "en": "Health & audit",
        "tr": "Sağlık & denetim",
    },
    "ui.dash.active_projects": {
        "en": "Active projects",
        "tr": "Aktif projeler",
    },
    "ui.dash.all": {
        "en": "All",
        "tr": "Tümü",
    },
    # UI chrome — supersession candidates view
    "ui.cand.heading": {
        "en": "Supersession candidates",
        "tr": "Supersession adayları",
    },
    "ui.cand.role_old": {
        "en": "Old — will be superseded",
        "tr": "Eski — yenilenecek",
    },
    "ui.cand.role_new": {
        "en": "New — current record",
        "tr": "Yeni — güncel kayıt",
    },
    "ui.btn.swap": {
        "en": "swap direction",
        "tr": "yön değiştir",
    },
    "ui.btn.approve": {
        "en": "Approve",
        "tr": "Onayla",
    },
    "ui.btn.reject": {
        "en": "Reject",
        "tr": "Reddet",
    },
    "ui.btn.link": {
        "en": "Link — target: new/current record",
        "tr": "Bağla — hedef: yeni/güncel kayıt",
    },
    "ui.btn.dismiss": {
        "en": "Dismiss",
        "tr": "Yoksay",
    },
    "ui.cand.loading": {
        "en": "Loading…",
        "tr": "Yükleniyor…",
    },
    "ui.cand.no_candidates": {
        "en": "No candidates. If the graph is stale, run consolidation first.",
        "tr": "Aday yok. Graf güncel değilse önce birleştirme çalıştırın.",
    },
    # UI chrome — list view
    "ui.list.heading.decisions": {
        "en": "Decisions",
        "tr": "Kararlar",
    },
    "ui.list.heading.lessons": {
        "en": "Lessons",
        "tr": "Dersler",
    },
    "ui.list.queue_mode": {
        "en": "Queue mode",
        "tr": "Kuyruk modu",
    },
    "ui.list.filter.all": {
        "en": "All",
        "tr": "Tümü",
    },
    "ui.list.all_projects": {
        "en": "all projects",
        "tr": "tüm projeler",
    },
    "ui.list.bulk.accept": {
        "en": "Accept selected",
        "tr": "Seçilenleri onayla",
    },
    "ui.list.bulk.reject": {
        "en": "Reject selected",
        "tr": "Seçilenleri reddet",
    },
    "ui.list.bulk.clear": {
        "en": "Clear",
        "tr": "Temizle",
    },
    # UI chrome — queue view
    "ui.queue.complete": {
        "en": "Queue complete",
        "tr": "Kuyruk tamamlandı",
    },
    "ui.queue.back_to_list": {
        "en": "Back to list",
        "tr": "Listeye dön",
    },
    "ui.queue.skip": {
        "en": "Skip",
        "tr": "Atla",
    },
    "ui.queue.hint.approve": {
        "en": "approve",
        "tr": "onayla",
    },
    "ui.queue.hint.reject": {
        "en": "reject",
        "tr": "reddet",
    },
    "ui.queue.hint.skip": {
        "en": "skip",
        "tr": "atla",
    },
    "ui.queue.hint.exit": {
        "en": "exit",
        "tr": "çık",
    },
    # UI chrome — health view
    "ui.health.inconsistencies": {
        "en": "Inconsistencies",
        "tr": "Tutarsızlıklar",
    },
    "ui.health.stale_proposed": {
        "en": "Stale 'proposed'",
        "tr": "Bayat 'önerilen'",
    },
    "ui.health.missing_source": {
        "en": "Missing source",
        "tr": "Eksik kaynak",
    },
    "ui.health.possible_duplicates": {
        "en": "Possible duplicates",
        "tr": "Olası kopyalar",
    },
    # UI chrome — search view
    "ui.search.hint": {
        "en": "decision, lesson, tag, content… (e.g. embedding, deadlock, canary)",
        "tr": "karar, ders, etiket, içerik… (örn. embedding, deadlock, canary)",
    },
    # UI chrome — detail view
    "ui.detail.edit": {
        "en": "Edit",
        "tr": "Düzenle",
    },
}

_resolved_lang: str | None = None
_apple_locale: str | None = None
_apple_locale_checked = False


def _normalize_lang(value: str | None) -> str | None:
    if not value:
        return None
    primary = LOCALE_SUBTAG_SEPARATORS.split(value.strip(), maxsplit=1)[0].lower()
    return primary or None


def _read_apple_locale() -> str | None:
    global _apple_locale, _apple_locale_checked
    if _apple_locale_checked:
        return _apple_locale
    _apple_locale_checked = True
    try:
        result = subprocess.run(
            APPLE_LOCALE_CMD,
            capture_output=True,
            text=True,
            timeout=APPLE_LOCALE_TIMEOUT_SECONDS,
            check=False,
        )
        _apple_locale = result.stdout.strip() or None
    except Exception:
        logger.debug("AppleLocale lookup failed", exc_info=True)
        _apple_locale = None
    return _apple_locale


def _resolve_lang_uncached() -> str:
    for env_var in LANG_ENV_VARS:
        lang = _normalize_lang(os.environ.get(env_var))
        if lang in SUPPORTED_LANGS:
            return lang
    lang = _normalize_lang(_read_apple_locale())
    if lang in SUPPORTED_LANGS:
        return lang
    return DEFAULT_LANG


def resolve_lang() -> str:
    global _resolved_lang
    if _resolved_lang is None:
        _resolved_lang = _resolve_lang_uncached()
    return _resolved_lang


def reset_lang_cache() -> None:
    global _resolved_lang, _apple_locale, _apple_locale_checked
    _resolved_lang = None
    _apple_locale = None
    _apple_locale_checked = False


def t(key: str) -> str:
    translations = MESSAGES.get(key)
    if translations is None:
        raise KeyError(f"unknown i18n message key: {key!r}")
    text = translations.get(resolve_lang())
    if text is None:
        return translations[DEFAULT_LANG]
    return text


def ui_strings() -> dict[str, str]:
    """Return all ``ui.*`` catalog keys localized to the current language."""
    return {key: t(key) for key in MESSAGES if key.startswith("ui.")}
