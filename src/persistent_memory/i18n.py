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
    "decision_recall.protocol": {
        "en": (
            "## Decision-memory operating rule\n"
            "If this message needs a decision, analysis, investigation, or plan: treat "
            "relevant memory records as active constraints; verify uncertain decisions "
            "against source files, logs, tests, or data; for review/investigate/evaluate "
            "requests, first present findings, options, risks, and recommendation, and "
            "do not start code changes unless approval or implementation intent is clear; "
            "when implementation is decided, plan verification/tests too."
        ),
        "tr": (
            "## Karar hafızası çalışma kuralı\n"
            "Bu mesaj karar, analiz, araştırma veya planlama gerektiriyorsa: ilgili "
            "hafıza kayıtlarını aktif kısıt olarak kullan; emin olmadığın kararları "
            "kaynak dosyalar, loglar, testler veya veriyle doğrula; kontrol et/incele/"
            "değerlendir/araştır isteklerinde önce bulgu, seçenek, risk ve öneriyi sun, "
            "onay veya uygulama niyeti net değilse kod değişikliği başlatma; uygulama "
            "kararı netleşirse doğrulama/test adımını da planla."
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
    "ui.nav.council": {
        "en": "Council",
        "tr": "Konsey",
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
    "ui.live.new_records": {
        "en": "new records",
        "tr": "yeni kayıt",
    },
    "ui.live.new_record_single": {
        "en": "new record",
        "tr": "yeni kayıt",
    },
    "ui.live.go_to_list": {
        "en": "Go to list",
        "tr": "Listeye git",
    },
    "ui.live.live": {
        "en": "Live",
        "tr": "Canlı",
    },
    "ui.live.offline": {
        "en": "Offline",
        "tr": "Çevrimdışı",
    },
    "ui.live.reconnecting": {
        "en": "Reconnecting…",
        "tr": "Yeniden bağlanıyor…",
    },
    "ui.live.stream_status": {
        "en": "Record stream",
        "tr": "Kayıt akışı",
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
    # UI chrome — AI council board view
    "ui.council.eyebrow": {
        "en": "AI Council · live board",
        "tr": "AI Konseyi · canlı akış",
    },
    "ui.council.heading": {
        "en": "Council",
        "tr": "Konsey",
    },
    "ui.council.live": {
        "en": "Live",
        "tr": "Canlı",
    },
    "ui.council.paused": {
        "en": "Paused",
        "tr": "Duraklatıldı",
    },
    "ui.council.updated": {
        "en": "updated",
        "tr": "güncellendi",
    },
    "ui.council.project": {
        "en": "Project",
        "tr": "Proje",
    },
    "ui.council.thread": {
        "en": "Thread",
        "tr": "İş parçacığı",
    },
    "ui.council.all_threads": {
        "en": "All threads",
        "tr": "Tüm iş parçacıkları",
    },
    "ui.council.empty": {
        "en": "No messages in this project yet",
        "tr": "Bu projede henüz mesaj yok",
    },
    "ui.council.placeholder": {
        "en": "Write a note for the council…",
        "tr": "Konsey için bir not yaz…",
    },
    "ui.council.send": {
        "en": "Send",
        "tr": "Gönder",
    },
    "ui.council.send_failed": {
        "en": "Send failed",
        "tr": "Gönderim başarısız",
    },
    "ui.council.turn": {
        "en": "turn",
        "tr": "tur",
    },
    "ui.council.fallback": {
        "en": "fallback",
        "tr": "yedek",
    },
    "ui.council.fallback_hint": {
        "en": "captured from stdout fallback",
        "tr": "stdout yedek yolundan yakalandı",
    },
    "ui.council.error": {
        "en": "Couldn't reach the council board",
        "tr": "Konsey panosuna ulaşılamadı",
    },
    "ui.council.error_hint": {
        "en": "The daemon may be unreachable. It will keep retrying automatically.",
        "tr": "Daemon'a ulaşılamıyor olabilir. Otomatik olarak yeniden denenecek.",
    },
    # UI chrome — AI council session panel
    "ui.council.tab_board": {
        "en": "Board",
        "tr": "Pano",
    },
    "ui.council.tab_sessions": {
        "en": "Sessions",
        "tr": "Oturumlar",
    },
    "ui.council.tab_prompt": {
        "en": "Prompt",
        "tr": "Prompt",
    },
    "ui.council.new_session": {
        "en": "New session",
        "tr": "Yeni oturum",
    },
    "ui.council.topic": {
        "en": "Topic",
        "tr": "Konu",
    },
    "ui.council.topic_placeholder": {
        "en": "What should the council decide?",
        "tr": "Konsey ne karar versin?",
    },
    "ui.council.cwd": {
        "en": "Working directory",
        "tr": "Çalışma dizini",
    },
    "ui.council.cwd_placeholder": {
        "en": "/absolute/path/to/project",
        "tr": "/mutlak/yol/proje",
    },
    "ui.council.rounds": {
        "en": "Rounds",
        "tr": "Tur sayısı",
    },
    "ui.council.dry_run": {
        "en": "Preview only (dry-run)",
        "tr": "Önce dene (dry-run)",
    },
    "ui.council.start_session": {
        "en": "Start session",
        "tr": "Oturumu başlat",
    },
    "ui.council.preview_btn": {
        "en": "Preview",
        "tr": "Önizle",
    },
    "ui.council.dry_run_notice": {
        "en": "Preview only — no session was started.",
        "tr": "Sadece önizleme — oturum başlatılmadı.",
    },
    "ui.council.preview_heading": {
        "en": "Prompt preview",
        "tr": "Prompt önizleme",
    },
    "ui.council.sessions_empty": {
        "en": "No sessions yet",
        "tr": "Henüz oturum yok",
    },
    "ui.council.select_session": {
        "en": "Select a session to see details",
        "tr": "Ayrıntılar için bir oturum seçin",
    },
    "ui.council.members": {
        "en": "members",
        "tr": "üye",
    },
    "ui.council.rounds_count": {
        "en": "rounds",
        "tr": "tur",
    },
    "ui.council.created_at": {
        "en": "created",
        "tr": "oluşturuldu",
    },
    "ui.council.record_link": {
        "en": "record",
        "tr": "kayıt",
    },
    "ui.council.cancel": {
        "en": "Cancel",
        "tr": "İptal et",
    },
    "ui.council.cancel_confirm": {
        "en": "Cancel this session?",
        "tr": "Bu oturum iptal edilsin mi?",
    },
    "ui.council.yes": {
        "en": "Yes",
        "tr": "Evet",
    },
    "ui.council.no": {
        "en": "No",
        "tr": "Hayır",
    },
    "ui.council.cancel_failed": {
        "en": "Cancel failed",
        "tr": "İptal başarısız",
    },
    "ui.council.turn_matrix": {
        "en": "Turn matrix",
        "tr": "Tur matrisi",
    },
    "ui.council.synthesis_row": {
        "en": "Synthesis",
        "tr": "Sentez",
    },
    "ui.council.round_row_prefix": {
        "en": "Round",
        "tr": "Tur",
    },
    "ui.council.session_thread_heading": {
        "en": "Session activity",
        "tr": "Oturum akışı",
    },
    "ui.council.session_error": {
        "en": "Couldn't start session",
        "tr": "Oturum başlatılamadı",
    },
    "ui.council.session_detail_error": {
        "en": "Couldn't load session",
        "tr": "Oturum yüklenemedi",
    },
    "ui.council.no_synthesis_yet": {
        "en": "Not reached yet",
        "tr": "Henüz ulaşılmadı",
    },
    # UI chrome — AI council prompt tab
    "ui.council.prompt_editor_heading": {
        "en": "Global prompt",
        "tr": "Genel prompt",
    },
    "ui.council.prompt_is_default": {
        "en": "This is the default prompt — not yet customized.",
        "tr": "Bu varsayılan prompt — henüz özelleştirilmedi.",
    },
    "ui.council.prompt_load_error": {
        "en": "Couldn't load the prompt",
        "tr": "Prompt yüklenemedi",
    },
    "ui.council.save_prompt": {
        "en": "Save",
        "tr": "Kaydet",
    },
    "ui.council.prompt_saved": {
        "en": "Prompt saved",
        "tr": "Prompt kaydedildi",
    },
    "ui.council.prompt_save_failed": {
        "en": "Couldn't save prompt",
        "tr": "Prompt kaydedilemedi",
    },
    "ui.council.reset_prompt": {
        "en": "Reset to default",
        "tr": "Varsayılana dön",
    },
    "ui.council.reset_confirm": {
        "en": "Reset to the default prompt?",
        "tr": "Varsayılan prompta dönülsün mü?",
    },
    "ui.council.reset_failed": {
        "en": "Reset failed",
        "tr": "Sıfırlama başarısız",
    },
    "ui.council.prompt_conflict": {
        "en": "Prompt was changed elsewhere — reload before saving again.",
        "tr": "Prompt başka bir yerden değiştirildi — tekrar kaydetmeden önce yeniden yükleyin.",
    },
    "ui.council.reload_prompt": {
        "en": "Reload",
        "tr": "Yeniden yükle",
    },
    "ui.council.layer_preview_heading": {
        "en": "Active layers",
        "tr": "Etkin katmanlar",
    },
    "ui.council.layer_preview_hint": {
        "en": "See which prompt layers apply for a given project directory",
        "tr": "Belirli bir proje dizini için hangi prompt katmanlarının uygulandığını gör",
    },
    "ui.council.show_layers": {
        "en": "Show layers",
        "tr": "Katmanları göster",
    },
    "ui.council.layers_error": {
        "en": "Couldn't load layers",
        "tr": "Katmanlar yüklenemedi",
    },
    "ui.council.config_heading": {
        "en": "Project configuration",
        "tr": "Proje yapılandırması",
    },
    "ui.council.config_readonly_note": {
        "en": "Read-only — edit .pm-council.yaml in the repo to change this",
        "tr": "Salt okunur — değiştirmek için repodaki .pm-council.yaml dosyasını düzenleyin",
    },
    "ui.council.config_source_default": {
        "en": "No .pm-council.yaml found — using built-in defaults",
        "tr": ".pm-council.yaml bulunamadı — yerleşik varsayılanlar kullanılıyor",
    },
    "ui.council.config_source_file": {
        "en": "loaded from",
        "tr": "kaynak dosya",
    },
    "ui.council.turn_timeout": {
        "en": "turn timeout (s)",
        "tr": "tur zaman aşımı (sn)",
    },
    # UI chrome — AI council live stream + all-projects sessions view
    "ui.council.all_projects": {
        "en": "All projects",
        "tr": "Tüm projeler",
    },
    "ui.council.this_project_only": {
        "en": "This project only",
        "tr": "Sadece bu proje",
    },
    "ui.council.live_connected": {
        "en": "stream",
        "tr": "akış",
    },
    "ui.council.live_reconnecting": {
        "en": "Reconnecting…",
        "tr": "Yeniden bağlanıyor…",
    },
    "ui.council.live_polling": {
        "en": "Polling",
        "tr": "Yoklama modu",
    },
    "ui.council.running_now": {
        "en": "running now",
        "tr": "çalışıyor",
    },
    "ui.council.project_badge": {
        "en": "council sessions in this project",
        "tr": "bu projedeki konsey oturumları",
    },
    "ui.council.sessions_all_empty": {
        "en": "No council sessions in any project yet",
        "tr": "Hiçbir projede henüz konsey oturumu yok",
    },
    # UI chrome — AI council pixel scene
    "ui.council.scene.waiting": {
        "en": "Waiting",
        "tr": "Bekliyor",
    },
    "ui.council.scene.thinking": {
        "en": "Thinking",
        "tr": "Düşünüyor",
    },
    "ui.council.scene.speaking": {
        "en": "Speaking",
        "tr": "Konuşuyor",
    },
    "ui.council.scene.done": {
        "en": "Done",
        "tr": "Bitti",
    },
    "ui.council.scene.timeout": {
        "en": "Timed out",
        "tr": "Zaman aşımı",
    },
    "ui.council.scene.failed": {
        "en": "Failed",
        "tr": "Başarısız",
    },
    "ui.council.scene.skipped": {
        "en": "Skipped",
        "tr": "Atlandı",
    },
    "ui.council.scene.spokesperson": {
        "en": "Spokesperson",
        "tr": "Sözcü",
    },
    "ui.council.scene.round_progress": {
        "en": "Round",
        "tr": "Tur",
    },
    "ui.council.scene.synthesis": {
        "en": "Synthesis",
        "tr": "Sentez",
    },
    "ui.council.scene.last_word": {
        "en": "Last word",
        "tr": "Son söz",
    },
    "ui.council.scene.no_active_session": {
        "en": "No active session to show",
        "tr": "Gösterilecek etkin oturum yok",
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
    # UI chrome — graph view
    "ui.graph.eyebrow": {
        "en": "Cross-project knowledge graph",
        "tr": "Projeler arası bilgi grafiği",
    },
    "ui.graph.heading": {
        "en": "Graph",
        "tr": "Graf",
    },
    "ui.graph.unexpected_links": {
        "en": "Unexpected links",
        "tr": "Beklenmedik bağlantılar",
    },
    "ui.graph.reset": {
        "en": "Reset",
        "tr": "Sıfırla",
    },
    "ui.graph.table_toggle_show": {
        "en": "Table view",
        "tr": "Tablo görünümü",
    },
    "ui.graph.table_toggle_hide": {
        "en": "Graph view",
        "tr": "Graf görünümü",
    },
    "ui.graph.search_label": {
        "en": "Search graph nodes by id, title or project",
        "tr": "Graf düğümlerini kimlik, başlık veya projeye göre ara",
    },
    "ui.graph.search_placeholder": {
        "en": "Search nodes…",
        "tr": "Düğüm ara…",
    },
    "ui.graph.match_one": {
        "en": "match",
        "tr": "eşleşme",
    },
    "ui.graph.match_many": {
        "en": "matches",
        "tr": "eşleşme",
    },
    "ui.graph.chip_decision": {
        "en": "Decision",
        "tr": "Karar",
    },
    "ui.graph.chip_lesson": {
        "en": "Lesson",
        "tr": "Ders",
    },
    "ui.graph.chip_accepted": {
        "en": "Accepted",
        "tr": "Kabul edildi",
    },
    "ui.graph.chip_proposed": {
        "en": "Proposed",
        "tr": "Önerildi",
    },
    "ui.graph.chip_other": {
        "en": "Other",
        "tr": "Diğer",
    },
    "ui.graph.all_projects": {
        "en": "All projects",
        "tr": "Tüm projeler",
    },
    "ui.graph.project_filter_label": {
        "en": "Filter by project",
        "tr": "Projeye göre filtrele",
    },
    "ui.graph.active_filters": {
        "en": "active",
        "tr": "aktif",
    },
    "ui.graph.clear": {
        "en": "Clear",
        "tr": "Temizle",
    },
    "ui.graph.settling": {
        "en": "Settling layout…",
        "tr": "Yerleşim oturuyor…",
    },
    "ui.graph.stat_visible_nodes": {
        "en": "visible nodes",
        "tr": "görünür düğüm",
    },
    "ui.graph.stat_edges": {
        "en": "edges",
        "tr": "kenar",
    },
    "ui.graph.stat_clusters": {
        "en": "clusters",
        "tr": "küme",
    },
    "ui.graph.stat_isolated": {
        "en": "isolated",
        "tr": "izole",
    },
    "ui.graph.canvas_hint": {
        "en": (
            "sample of the {count}-node graph · scroll to zoom, drag to pan · "
            "click to select · double-click or the panel button to open the record"
        ),
        "tr": (
            "{count} düğümlük grafiğin örneklemi · yakınlaştırmak için kaydır, kaydırmak için sürükle · "
            "tıkla: seç · çift tıkla veya panelden kayda git"
        ),
    },
    "ui.graph.legend_small_cluster": {
        "en": "small cluster",
        "tr": "küçük küme",
    },
    "ui.graph.tooltip_decision": {
        "en": "decision",
        "tr": "karar",
    },
    "ui.graph.tooltip_lesson": {
        "en": "lesson",
        "tr": "ders",
    },
    "ui.graph.legend_heading": {
        "en": "Legend",
        "tr": "Gösterge",
    },
    "ui.graph.legend_type_heading": {
        "en": "Type",
        "tr": "Tür",
    },
    "ui.graph.legend_decision": {
        "en": "Decision",
        "tr": "Karar",
    },
    "ui.graph.legend_decision_shape": {
        "en": "circle",
        "tr": "daire",
    },
    "ui.graph.legend_lesson": {
        "en": "Lesson",
        "tr": "Ders",
    },
    "ui.graph.legend_lesson_shape": {
        "en": "diamond",
        "tr": "elmas",
    },
    "ui.graph.legend_status_heading": {
        "en": "Status",
        "tr": "Durum",
    },
    "ui.graph.status_accepted": {
        "en": "Accepted",
        "tr": "Kabul edildi",
    },
    "ui.graph.status_accepted_style": {
        "en": "solid ring",
        "tr": "düz halka",
    },
    "ui.graph.status_proposed": {
        "en": "Proposed",
        "tr": "Önerildi",
    },
    "ui.graph.status_proposed_style": {
        "en": "dashed ring",
        "tr": "kesikli halka",
    },
    "ui.graph.status_reverted": {
        "en": "Reverted",
        "tr": "Geri alındı",
    },
    "ui.graph.status_reverted_style": {
        "en": "thick ring",
        "tr": "kalın halka",
    },
    "ui.graph.status_superseded": {
        "en": "Superseded",
        "tr": "Değiştirildi",
    },
    "ui.graph.status_superseded_style": {
        "en": "dashed muted ring",
        "tr": "kesikli soluk halka",
    },
    "ui.graph.legend_edge_heading": {
        "en": "Edge type",
        "tr": "Kenar türü",
    },
    "ui.graph.edge_conceptually_related_to": {
        "en": "Conceptually related",
        "tr": "Kavramsal olarak ilişkili",
    },
    "ui.graph.edge_semantically_similar_to": {
        "en": "Semantically similar",
        "tr": "Anlamsal olarak benzer",
    },
    "ui.graph.edge_rationale_for": {
        "en": "Rationale for",
        "tr": "Gerekçe",
    },
    "ui.graph.edge_shares_data_with": {
        "en": "Shares data with",
        "tr": "Veri paylaşıyor",
    },
    "ui.graph.legend_unexpected": {
        "en": "Unexpected link",
        "tr": "Beklenmedik bağlantı",
    },
    "ui.graph.legend_unexpected_style": {
        "en": "glow + flow",
        "tr": "parıltı + akış",
    },
    "ui.graph.selected_heading": {
        "en": "Selected",
        "tr": "Seçili",
    },
    "ui.graph.clear_selection": {
        "en": "Clear selection",
        "tr": "Seçimi temizle",
    },
    "ui.graph.record_not_found": {
        "en": "Record not found",
        "tr": "Kayıt bulunamadı",
    },
    "ui.graph.date": {
        "en": "Date",
        "tr": "Tarih",
    },
    "ui.graph.importance": {
        "en": "Importance",
        "tr": "Önem",
    },
    "ui.graph.go_to_record": {
        "en": "Go to record",
        "tr": "Kayda git",
    },
    "ui.graph.neighbors": {
        "en": "Neighbors",
        "tr": "Komşular",
    },
    "ui.graph.no_neighbors": {
        "en": "No neighbors",
        "tr": "Komşu yok",
    },
    "ui.graph.clusters_heading": {
        "en": "Clusters",
        "tr": "Kümeler",
    },
    "ui.graph.show_less": {
        "en": "Show less",
        "tr": "Daha az göster",
    },
    "ui.graph.show_more": {
        "en": "More",
        "tr": "Daha fazla",
    },
    "ui.graph.unexpected_heading": {
        "en": "Unexpected connections",
        "tr": "Beklenmedik bağlantılar",
    },
    "ui.graph.table_caption": {
        "en": "Accessible list of graph nodes",
        "tr": "Graf düğümlerinin erişilebilir listesi",
    },
    "ui.graph.table_col_id": {
        "en": "ID",
        "tr": "Kimlik",
    },
    "ui.graph.table_col_title": {
        "en": "Title",
        "tr": "Başlık",
    },
    "ui.graph.table_col_type": {
        "en": "Type",
        "tr": "Tür",
    },
    "ui.graph.table_col_status": {
        "en": "Status",
        "tr": "Durum",
    },
    "ui.graph.table_col_project": {
        "en": "Project",
        "tr": "Proje",
    },
    "ui.graph.table_col_degree": {
        "en": "Degree",
        "tr": "Derece",
    },
    "ui.graph.table_empty": {
        "en": "No nodes match the current filters",
        "tr": "Geçerli filtrelere uyan düğüm yok",
    },
    # UI chrome — agent rules & memory view
    "ui.nav.agents": {
        "en": "Agent rules & memory",
        "tr": "Ajan kuralları & hafızası",
    },
    "ui.agents.heading": {
        "en": "Agent rules & memory",
        "tr": "Ajan kuralları & hafızası",
    },
    "ui.agents.edit": {"en": "Edit", "tr": "Düzenle"},
    "ui.agents.save": {"en": "Save", "tr": "Kaydet"},
    "ui.agents.saved": {"en": "Saved", "tr": "Kaydedildi"},
    "ui.agents.unsaved_warning": {
        "en": "You have unsaved changes. Discard them?",
        "tr": "Kaydedilmemiş değişiklikler var. Gözden çıkarılsın mı?",
    },
    "ui.agents.empty": {
        "en": "Select a file from the left.",
        "tr": "Soldan bir dosya seç.",
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
