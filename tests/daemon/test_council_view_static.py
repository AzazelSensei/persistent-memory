import json
import re

from starlette.testclient import TestClient

from persistent_memory.daemon.app import STATIC_DIR, TEMPLATES_DIR, create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.i18n import reset_lang_cache
from tests.daemon.jsx_runtime import run_extracted_functions

PM_STATIC = STATIC_DIR / "pm"


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _parse_i18n(body: str) -> dict:
    start = body.index("window.PM_I18N = ") + len("window.PM_I18N = ")
    end = body.index(";", start)
    return json.loads(body[start:end])


def test_app_page_loads_council_view(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "views-council.jsx" in resp.text
    assert "fetchCouncilBoard" in resp.text
    assert "fetchCouncilThreads" in resp.text
    assert "postCouncilBoard" in resp.text


def test_council_static_file_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/pm/views-council.jsx")
    assert resp.status_code == 200
    assert "PMCouncil" in resp.text


def test_nav_registers_council_view():
    app_jsx = (PM_STATIC / "app.jsx").read_text(encoding="utf-8")
    assert '"council"' in app_jsx
    assert "PMCouncil" in app_jsx


def test_template_wires_council_script():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "/static/pm/views-council.jsx" in html
    assert "/api/council/board" in html


def test_council_view_calls_board_endpoints():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "fetchCouncilBoard" in council_jsx
    assert "postCouncilBoard" in council_jsx
    assert "POLL_INTERVAL_MS" in council_jsx
    assert "clearInterval" in council_jsx


def test_council_view_never_uses_dangerous_html():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in council_jsx


def test_app_page_turkish_i18n_has_council_nav_label(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_LANG", "tr")
    reset_lang_cache()
    try:
        client = _client(tmp_path)
        resp = client.get("/")
        assert resp.status_code == 200
        i18n_data = _parse_i18n(resp.text)
        assert i18n_data.get("ui.nav.council") == "Konsey"
        assert i18n_data.get("ui.council.empty") == "Bu projede henüz mesaj yok"
    finally:
        monkeypatch.delenv("PM_LANG", raising=False)
        reset_lang_cache()


def test_council_view_refbadge_guards_prototype_pollution():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "hasOwnProperty" in council_jsx
    assert "REF_ID_RE" in council_jsx
    assert re.search(r"\[DLP\]-\\d\{4\}", council_jsx)


def test_council_view_guards_stale_project_response():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "let active = true" in council_jsx
    assert "active = false" in council_jsx
    assert "data.project" in council_jsx
    assert "data.thread" in council_jsx


def test_council_view_uses_inflight_guard_and_dedupe_merge():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "inFlightRef" in council_jsx
    assert "new Set(" in council_jsx
    assert re.search(r"prev\.concat\(", council_jsx) is None


def test_council_view_caps_message_list_and_memoizes_card():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "MAX_MESSAGES = 500" in council_jsx
    assert "React.memo(" in council_jsx


def test_council_view_shows_via_badge():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "cn-via" in council_jsx
    assert "msg.via" in council_jsx


def test_council_view_refreshes_threads_on_new_message():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "refreshThreads" in council_jsx


def test_council_view_switches_filter_to_draft_thread_on_send():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "sentThread" in council_jsx
    assert "setThread(sentThread)" in council_jsx


def test_council_view_refs_key_includes_index():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert 're.compile' not in council_jsx  # sanity: still plain jsx, no stray python
    assert re.search(r'key=\{r \+ "-" \+ i', council_jsx) or re.search(r'key=\{r \+ "-" \+ index', council_jsx)


def test_council_view_defines_l_sel_locally():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    css_block = council_jsx[council_jsx.index("pm-council-css") : council_jsx.index("document.head.appendChild")]
    assert ".l-sel{" in css_block


def test_post_council_board_surfaces_error_detail():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    post_block = html[html.index("postCouncilBoard: function") :]
    post_block = post_block[: post_block.index("fetchCouncilBoard") if "fetchCouncilBoard" in post_block else len(post_block)]
    assert "detail" in post_block


def test_council_fetch_helpers_return_ok_status_shape():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "ok: r.ok" in html


def test_council_view_has_error_state_handling():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "loadError" in council_jsx
    assert "ui.council.error" in council_jsx
    assert "ui.council.error_hint" in council_jsx


def test_i18n_has_council_error_keys_in_both_languages(tmp_path, monkeypatch):
    for lang, expected_nonempty in (("en", True), ("tr", True)):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            assert i18n_data.get("ui.council.error")
            assert i18n_data.get("ui.council.error_hint")
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


# ---- Faz 4a: session panel -------------------------------------------------

COUNCIL_SESSION_I18N_KEYS = [
    "ui.council.tab_board",
    "ui.council.tab_sessions",
    "ui.council.tab_prompt",
    "ui.council.new_session",
    "ui.council.topic",
    "ui.council.topic_placeholder",
    "ui.council.cwd",
    "ui.council.cwd_placeholder",
    "ui.council.rounds",
    "ui.council.dry_run",
    "ui.council.start_session",
    "ui.council.preview_btn",
    "ui.council.dry_run_notice",
    "ui.council.preview_heading",
    "ui.council.sessions_empty",
    "ui.council.select_session",
    "ui.council.members",
    "ui.council.rounds_count",
    "ui.council.created_at",
    "ui.council.record_link",
    "ui.council.cancel",
    "ui.council.cancel_confirm",
    "ui.council.yes",
    "ui.council.no",
    "ui.council.cancel_failed",
    "ui.council.turn_matrix",
    "ui.council.synthesis_row",
    "ui.council.round_row_prefix",
    "ui.council.session_thread_heading",
    "ui.council.session_error",
    "ui.council.session_detail_error",
    "ui.council.no_synthesis_yet",
]


def test_i18n_has_council_session_keys_in_both_languages(tmp_path, monkeypatch):
    for lang in ("en", "tr"):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            for key in COUNCIL_SESSION_I18N_KEYS:
                assert i18n_data.get(key), f"missing/empty {key} for lang={lang}"
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


def test_council_view_has_tab_infrastructure():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert 'useState("board")' in council_jsx
    assert "ui.council.tab_board" in council_jsx
    assert "ui.council.tab_sessions" in council_jsx
    assert "ui.council.tab_prompt" in council_jsx


def test_council_view_calls_session_endpoints():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "fetchCouncilSessions" in council_jsx
    assert "fetchCouncilSession(" in council_jsx
    assert "postCouncilSession" in council_jsx
    assert "cancelCouncilSession" in council_jsx


def test_app_html_wires_session_api_wrappers():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "fetchCouncilSessions: function" in html
    assert "fetchCouncilSession: function" in html
    assert "postCouncilSession: function" in html
    assert "cancelCouncilSession: function" in html
    assert "/api/council/sessions" in html


def test_council_view_cancel_requires_confirmation_step():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "cancelConfirm" in council_jsx
    assert "ui.council.cancel_confirm" in council_jsx
    # the confirm-state gate must be declared before the actual cancel call
    # site, i.e. the cancel click can't reach the API without passing through it.
    assert council_jsx.index("cancelConfirm") < council_jsx.index("cancelCouncilSession")


def test_council_view_renders_turn_matrix():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "session.turns" in council_jsx or "selectedSession.turns" in council_jsx
    assert "ui.council.turn_matrix" in council_jsx
    assert "ui.council.synthesis_row" in council_jsx


def test_council_view_supports_dry_run_preview():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "dry_run" in council_jsx
    assert "prompts" in council_jsx
    assert "ui.council.preview_heading" in council_jsx


def test_council_view_stops_polling_when_session_inactive():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "ACTIVE_SESSION_STATUSES" in council_jsx
    assert council_jsx.count("clearInterval") >= 2


def test_council_view_session_form_requires_topic_and_cwd():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "formTopic" in council_jsx
    assert "formCwd" in council_jsx


def test_council_view_never_uses_dangerous_html_after_sessions_expansion():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in council_jsx


# ---- Faz 4b: prompt tab ----------------------------------------------------

COUNCIL_PROMPT_I18N_KEYS = [
    "ui.council.prompt_editor_heading",
    "ui.council.prompt_is_default",
    "ui.council.prompt_load_error",
    "ui.council.save_prompt",
    "ui.council.prompt_saved",
    "ui.council.prompt_save_failed",
    "ui.council.reset_prompt",
    "ui.council.reset_confirm",
    "ui.council.reset_failed",
    "ui.council.layer_preview_heading",
    "ui.council.layer_preview_hint",
    "ui.council.show_layers",
    "ui.council.layers_error",
    "ui.council.config_heading",
    "ui.council.config_readonly_note",
    "ui.council.config_source_default",
    "ui.council.config_source_file",
    "ui.council.turn_timeout",
]


def test_council_prompt_component_file_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/pm/views-council-prompt.jsx")
    assert resp.status_code == 200
    assert "PMCouncilPrompt" in resp.text


def test_template_wires_council_prompt_script():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "/static/pm/views-council-prompt.jsx" in html
    assert "/api/council/prompt" in html
    assert "/api/council/config" in html


def test_app_html_wires_prompt_api_wrappers():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "fetchCouncilPrompt: function" in html
    assert "saveCouncilPrompt: function" in html
    assert "resetCouncilPrompt: function" in html
    assert "fetchCouncilConfig: function" in html
    assert "/api/council/prompt/reset" in html


def test_council_prompt_view_never_uses_dangerous_html():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in prompt_jsx


def test_council_prompt_view_calls_prompt_endpoints():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "fetchCouncilPrompt" in prompt_jsx
    assert "saveCouncilPrompt" in prompt_jsx
    assert "resetCouncilPrompt" in prompt_jsx
    assert "fetchCouncilConfig" in prompt_jsx


def test_council_prompt_view_reset_requires_confirmation():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "resetConfirm" in prompt_jsx
    assert "ui.council.reset_confirm" in prompt_jsx
    assert prompt_jsx.index("resetConfirm") < prompt_jsx.index("resetCouncilPrompt")


def test_council_prompt_view_shows_default_indicator():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "is_default" in prompt_jsx
    assert "ui.council.prompt_is_default" in prompt_jsx


def test_council_prompt_view_shows_char_counter():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "MAX_PROMPT_CHARS = 20000" in prompt_jsx
    assert "maxLength={MAX_PROMPT_CHARS}" in prompt_jsx


def test_council_prompt_view_min_height_editor():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert re.search(r"min-height:\s*40\d px|min-height:\s*4\d\dpx", prompt_jsx) or "min-height:400px" in prompt_jsx


def test_council_prompt_view_layer_preview_calls_config_endpoint():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "fetchCouncilConfig" in prompt_jsx
    assert "prompt_layers" in prompt_jsx
    assert "<details" in prompt_jsx


def test_council_prompt_view_shows_422_detail_on_save_error():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "res.detail" in prompt_jsx or "detail" in prompt_jsx


def test_council_prompt_view_renders_readonly_config_table():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "config_readonly_note" in prompt_jsx
    assert "config.members" in prompt_jsx
    assert "member.backend" in prompt_jsx or "m.backend" in prompt_jsx
    assert "saveCouncilConfig" not in prompt_jsx


def test_council_prompt_view_tab_uses_component():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "window.PMCouncilPrompt" in council_jsx


# ---- Faz 4-5 adversarial review fixes --------------------------------------


def test_turn_matrix_synthesis_row_uses_highest_round_not_hardcoded_rounds_plus_one():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "tn.round === session.rounds + 1" not in council_jsx
    assert re.search(r"\.reduce\(\s*\(acc, tn\)\s*=>\s*Math\.max\(acc, tn\.round\)", council_jsx)


def test_turn_matrix_prefers_done_turn_among_synthesis_candidates():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert re.search(r'synthesisTurns\.find\(\(tn\)\s*=>\s*tn\.status === "done"\)', council_jsx)


def test_turn_matrix_shows_missing_dash_not_pending_for_terminal_sessions():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "TERMINAL_SESSION_STATUSES" in council_jsx
    assert "MISSING_TURN_STATUS" in council_jsx


def test_turn_matrix_propagates_skipped_status_to_later_rounds():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "skippedMembers" in council_jsx
    assert re.search(r'status === "skipped"', council_jsx)


def test_cancel_yes_guards_against_stale_response_with_selected_id_ref():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "selectedIdRef" in council_jsx
    start = council_jsx.index("const onCancelYes")
    end = council_jsx.index("    return (", start)
    on_cancel_yes = council_jsx[start:end]
    assert "selectedIdRef.current === reqId" in on_cancel_yes


def test_refresh_sessions_requeues_instead_of_dropping_in_flight_request():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "listPendingRef" in council_jsx
    assert "projectRef" in council_jsx
    refresh_block = council_jsx[
        council_jsx.index("const refreshSessions") : council_jsx.index("const onSubmitForm")
    ]
    assert "currentProject !== projectRef.current" in refresh_block


def test_board_poll_has_inflight_guard_and_monotonic_cursor():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "boardInFlightRef" in council_jsx
    assert "messageSeq(" in council_jsx


def test_prompt_editor_sends_version_and_handles_conflict():
    prompt_jsx = (PM_STATIC / "views-council-prompt.jsx").read_text(encoding="utf-8")
    assert "res.version" in prompt_jsx or "body.version" in prompt_jsx
    assert "saveCouncilPrompt(text, version)" in prompt_jsx
    assert "409" in prompt_jsx
    assert "ui.council.prompt_conflict" in prompt_jsx
    assert "ui.council.reload_prompt" in prompt_jsx


def test_app_html_prompt_wrappers_carry_version():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    fetch_block = html[html.index("fetchCouncilPrompt: function") : html.index("saveCouncilPrompt: function")]
    assert "body.version" in fetch_block
    save_block = html[html.index("saveCouncilPrompt: function") : html.index("resetCouncilPrompt: function")]
    assert "version" in save_block


COUNCIL_PROMPT_CONFLICT_I18N_KEYS = [
    "ui.council.prompt_conflict",
    "ui.council.reload_prompt",
]


def test_i18n_has_council_prompt_conflict_keys_in_both_languages(tmp_path, monkeypatch):
    for lang in ("en", "tr"):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            for key in COUNCIL_PROMPT_CONFLICT_I18N_KEYS:
                assert i18n_data.get(key), f"missing/empty {key} for lang={lang}"
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


def test_i18n_has_council_prompt_keys_in_both_languages(tmp_path, monkeypatch):
    for lang in ("en", "tr"):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            for key in COUNCIL_PROMPT_I18N_KEYS:
                assert i18n_data.get(key), f"missing/empty {key} for lang={lang}"
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


# ---- Faz 6: anlik akis (SSE) + tum projeler gorunumu -----------------------

COUNCIL_LIVE_STREAM_I18N_KEYS = [
    "ui.council.all_projects",
    "ui.council.this_project_only",
    "ui.council.live_connected",
    "ui.council.live_reconnecting",
    "ui.council.live_polling",
    "ui.council.running_now",
    "ui.council.project_badge",
    "ui.council.sessions_all_empty",
]


def test_i18n_has_council_live_stream_keys_in_both_languages(tmp_path, monkeypatch):
    for lang in ("en", "tr"):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            for key in COUNCIL_LIVE_STREAM_I18N_KEYS:
                assert i18n_data.get(key), f"missing/empty {key} for lang={lang}"
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


def test_sessions_panel_fetches_all_projects_by_default():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "fetchAllCouncilSessions" in council_jsx
    assert "/api/council/sessions/all" in council_jsx
    assert 'useState(SESSION_SCOPE_ALL)' in council_jsx


def test_sessions_panel_has_scope_toggle():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "SESSION_SCOPE_ALL" in council_jsx
    assert "SESSION_SCOPE_PROJECT" in council_jsx
    assert "ui.council.all_projects" in council_jsx
    assert "ui.council.this_project_only" in council_jsx
    assert "setScope(SESSION_SCOPE_ALL)" in council_jsx
    assert "setScope(SESSION_SCOPE_PROJECT)" in council_jsx


def test_sessions_panel_shows_project_badge_only_in_all_scope():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "cn-projbadge" in council_jsx
    assert "scope === SESSION_SCOPE_ALL" in council_jsx


def test_sessions_panel_sorts_active_sessions_first():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "function sortSessionsActiveFirst" in council_jsx
    assert "ui.council.running_now" in council_jsx


def test_sessions_panel_row_click_syncs_project_when_different():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "onSelectProject" in council_jsx
    assert re.search(r"\bs\.project\s*!==\s*project\b", council_jsx)


def test_sessions_panel_detail_effect_keys_on_selected_project_not_toolbar_project():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "selectedProject" in council_jsx
    assert re.search(r"\[selectedProject, selectedId\]", council_jsx)


def test_sessions_panel_all_scope_has_distinct_empty_message():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "ui.council.sessions_all_empty" in council_jsx


def test_council_stream_url_builder_used_by_both_board_and_session_stream():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert council_jsx.count("councilStreamUrl(") >= 3


def test_council_stream_hook_opens_event_source():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "new EventSource(" in council_jsx
    assert 'addEventListener("message"' in council_jsx
    assert 'addEventListener("session"' in council_jsx


def test_council_stream_hook_ignores_ping_event():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert 'addEventListener("ping"' in council_jsx


def test_council_stream_hook_retries_once_then_falls_back_to_polling():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "retriedRef" in council_jsx
    assert "STREAM_STATUS_POLLING" in council_jsx
    assert "STREAM_STATUS_RECONNECTING" in council_jsx


def test_council_stream_hook_closes_event_source_on_cleanup():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    start = council_jsx.index("function useCouncilStream")
    end = council_jsx.index("function ConnectionIndicator", start)
    hook_body = council_jsx[start:end]
    assert "cancelled = true" in hook_body
    assert ".close()" in hook_body


def test_session_stream_disabled_when_session_not_active():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert re.search(r"selectedActive\s*&&\s*selectedProject\s*&&\s*selectedId", council_jsx)


def test_board_stream_disabled_outside_board_tab():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert re.search(r'tab === "board"[^\n]*&&[^\n]*live', council_jsx) or re.search(
        r'live[^\n]*&&[^\n]*tab === "board"', council_jsx
    )


def test_fallback_polling_effects_gated_on_stream_status_polling():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert council_jsx.count("STREAM_STATUS_POLLING") >= 3


def test_connection_indicator_renders_three_states():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "function ConnectionIndicator" in council_jsx
    assert "ui.council.live_connected" in council_jsx
    assert "ui.council.live_reconnecting" in council_jsx
    assert "ui.council.live_polling" in council_jsx


def test_project_selector_has_council_badge():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "function CouncilProjectBadge" in council_jsx
    assert "<CouncilProjectBadge" in council_jsx
    assert "cn-sel-badge" in council_jsx


def test_council_view_never_uses_dangerous_html_after_live_stream_expansion():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in council_jsx


def test_council_stream_hook_has_no_empty_catch_blocks():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert not re.search(r"catch\s*\([^)]*\)\s*\{\s*\}", council_jsx)


# ---- Faz 7: pixel-art sahne -------------------------------------------------

COUNCIL_SCENE_I18N_KEYS = [
    "ui.council.scene.waiting",
    "ui.council.scene.thinking",
    "ui.council.scene.speaking",
    "ui.council.scene.done",
    "ui.council.scene.timeout",
    "ui.council.scene.failed",
    "ui.council.scene.skipped",
    "ui.council.scene.spokesperson",
    "ui.council.scene.round_progress",
    "ui.council.scene.synthesis",
    "ui.council.scene.last_word",
    "ui.council.scene.no_active_session",
]


def test_council_scene_file_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/pm/views-council-scene.jsx")
    assert resp.status_code == 200
    assert "PMCouncilScene" in resp.text


def test_template_wires_council_scene_script():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "/static/pm/views-council-scene.jsx?v={{ pm_asset_version }}" in html


def test_council_scene_assigned_on_window():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "window.PMCouncilScene = CouncilScene" in scene_jsx


def test_council_view_renders_scene_component_above_turn_matrix():
    council_jsx = (PM_STATIC / "views-council.jsx").read_text(encoding="utf-8")
    assert "window.PMCouncilScene" in council_jsx
    assert council_jsx.index("window.PMCouncilScene") < council_jsx.index('ui.council.turn_matrix", "Turn matrix"')


def test_council_scene_defines_pixel_patterns_per_backend():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    for pattern_name in ("CLAUDE_HEAD", "CODEX_HEAD", "GROK_HEAD", "KIMI_HEAD", "GENERIC_HEAD", "SHOULDERS"):
        assert pattern_name in scene_jsx


SCENE_JSX_PATH = PM_STATIC / "views-council-scene.jsx"
HEAD_CONSTANT_NAMES = ("CLAUDE_HEAD", "CODEX_HEAD", "GROK_HEAD", "KIMI_HEAD", "GENERIC_HEAD")
SHOULDERS_CONSTANT_NAME = "SHOULDERS"
EXPECTED_GRID_W = 12
EXPECTED_HEAD_ROWS = 12
PIXEL_ALPHABET = {"0", "1"}


def _read_scene_jsx() -> str:
    return SCENE_JSX_PATH.read_text(encoding="utf-8")


def _parse_int_constant(source: str, name: str) -> int:
    match = re.search(r"const " + name + r"\s*=\s*(\d+);", source)
    assert match, f"{name} is not a plain integer constant in views-council-scene.jsx"
    return int(match.group(1))


def _parse_pixel_grid(source: str, name: str) -> list:
    match = re.search(r"const " + name + r"\s*=\s*\[(.*?)\];", source, re.DOTALL)
    assert match, f"{name} bitmap not found in views-council-scene.jsx"
    return re.findall(r'"([^"]*)"', match.group(1))


def _assert_grid_shape(name: str, rows: list, row_count: int, row_width: int) -> None:
    assert len(rows) == row_count, f"{name} has {len(rows)} rows, expected {row_count}"
    for index, row in enumerate(rows):
        assert len(row) == row_width, f"{name} row {index} is {len(row)} px wide, expected {row_width}"
        assert set(row) <= PIXEL_ALPHABET, f"{name} row {index} is not a binary bitmap: {row!r}"


def test_council_scene_pixel_patterns_are_distinct_12x12_grids():
    scene_jsx = _read_scene_jsx()
    grid_w = _parse_int_constant(scene_jsx, "GRID_W")
    grid_h = _parse_int_constant(scene_jsx, "GRID_H")
    assert grid_w == EXPECTED_GRID_W
    heads = {name: _parse_pixel_grid(scene_jsx, name) for name in HEAD_CONSTANT_NAMES}
    shoulders = _parse_pixel_grid(scene_jsx, SHOULDERS_CONSTANT_NAME)
    for name, rows in heads.items():
        _assert_grid_shape(name, rows, EXPECTED_HEAD_ROWS, grid_w)
    _assert_grid_shape(SHOULDERS_CONSTANT_NAME, shoulders, grid_h - EXPECTED_HEAD_ROWS, grid_w)
    assert EXPECTED_HEAD_ROWS + len(shoulders) == grid_h
    names = list(HEAD_CONSTANT_NAMES)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            assert heads[left] != heads[right], f"{left} and {right} are the same bitmap; avatars are indistinguishable"


def test_council_scene_maps_status_to_visual():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "MEMBER_STATUS_COLOR" in scene_jsx
    assert "MEMBER_STATUS_MARK" in scene_jsx
    for status in ("waiting", "thinking", "speaking", "done", "timeout", "failed", "skipped"):
        assert '"' + status + '"' in scene_jsx or "[MEMBER_STATUS_" + status.upper() + "]" in scene_jsx


def test_council_scene_respects_reduced_motion():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in scene_jsx


def test_council_scene_avatar_has_role_img_and_aria_label():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert 'role="img"' in scene_jsx
    assert "aria-label={" in scene_jsx


def test_council_scene_is_a_figure_element():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "<figure" in scene_jsx


def test_council_scene_never_uses_dangerous_html():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in scene_jsx


def test_council_scene_derives_state_from_existing_stream_data_not_new_eventsource():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "new EventSource(" not in scene_jsx


def test_i18n_has_council_scene_keys_in_both_languages(tmp_path, monkeypatch):
    for lang in ("en", "tr"):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            for key in COUNCIL_SCENE_I18N_KEYS:
                assert i18n_data.get(key), f"missing/empty {key} for lang={lang}"
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


def test_council_scene_never_shows_a_speaker_in_a_finished_session():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert 'TERMINAL_SESSION_STATUSES = ["converged", "failed", "cancelled"]' in scene_jsx
    assert "function isSessionLive(session)" in scene_jsx
    assert "if (!live) return MEMBER_STATUS_DONE;" in scene_jsx


def test_council_scene_draws_a_table_behind_the_seated_members():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert ".cns-table{" in scene_jsx
    assert 'className="cns-table"' in scene_jsx
    assert ".cns-seat{" in scene_jsx


def test_council_scene_bubble_strips_markdown_noise():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "MARKDOWN_NOISE_RE" in scene_jsx
    assert "plainPreview(lastMessage.body, BUBBLE_PREVIEW_CHARS)" in scene_jsx


def test_council_scene_does_not_claim_synthesis_phase_on_a_cancelled_session():
    scene_jsx = (PM_STATIC / "views-council-scene.jsx").read_text(encoding="utf-8")
    assert "function isSynthesisPhase(matrix, live)" in scene_jsx
    assert 'return !!matrix.synthesis && matrix.synthesis.status !== "pending";' in scene_jsx
    assert "isSynthesisPhase(matrix, live)" in scene_jsx


# ---- Faz 7 adversarial review fixes: scene behaviour under node -------------

SCENE_STATUS_CONSTANT_NAMES = (
    "MISSING_TURN_STATUS",
    "MEMBER_STATUS_WAITING",
    "MEMBER_STATUS_THINKING",
    "MEMBER_STATUS_SPEAKING",
    "MEMBER_STATUS_DONE",
    "MEMBER_STATUS_TIMEOUT",
    "MEMBER_STATUS_FAILED",
    "MEMBER_STATUS_SKIPPED",
)
SYNTHESIS_FN_NAMES = ("resolveSynthesisAuthor", "resolveMemberCell")
SPEAKER_FN_NAMES = (
    "deriveMemberStatus",
    "resolveSynthesisAuthor",
    "resolveMemberCell",
    "findSpeakingMemberId",
)
SPOKESPERSON_ID = "claude-1"
FALLBACK_ID = "codex-1"
THIRD_MEMBER_ID = "grok-1"
SYNTHESIS_MESSAGE_ID = "msg-synth"
REGULAR_ROUNDS = 2
SYNTHESIS_ROUND = REGULAR_ROUNDS + 1


def _parse_string_constant(source: str, name: str) -> str:
    match = re.search(r"const " + name + r'\s*=\s*"([^"]*)";', source)
    assert match, f"{name} is not a plain string constant in views-council-scene.jsx"
    return match.group(1)


def _scene_status_prelude() -> str:
    scene_jsx = _read_scene_jsx()
    return "\n".join(
        "const %s = %s;" % (name, json.dumps(_parse_string_constant(scene_jsx, name)))
        for name in SCENE_STATUS_CONSTANT_NAMES
    )


def _turn_cell(round_number: int, member_id: str, status: str, message_id=None) -> dict:
    return {"round": round_number, "member_id": member_id, "status": status, "message_id": message_id}


def _run_scene_functions(names, script_body: str, prelude_js: str = ""):
    return run_extracted_functions(
        path=SCENE_JSX_PATH,
        names=list(names),
        prelude_js=prelude_js,
        script_body=script_body,
    )


def _two_member_session() -> dict:
    return {
        "rounds": REGULAR_ROUNDS,
        "spokesperson": SPOKESPERSON_ID,
        "members": [SPOKESPERSON_ID, FALLBACK_ID],
    }


def _two_member_matrix(synthesis) -> dict:
    return {
        "rounds": [
            {
                "round": 1,
                "cells": [
                    _turn_cell(1, SPOKESPERSON_ID, "done", "m1"),
                    _turn_cell(1, FALLBACK_ID, "done", "m2"),
                ],
            },
            {
                "round": 2,
                "cells": [
                    _turn_cell(2, SPOKESPERSON_ID, "done", "m3"),
                    _turn_cell(2, FALLBACK_ID, "done", "m4"),
                ],
            },
        ],
        "synthesis": synthesis,
    }


def _resolve_synthesis_cells_script(session: dict, matrix: dict) -> str:
    return (
        "const session = %s;" % json.dumps(session)
        + "const matrix = %s;" % json.dumps(matrix)
        + "return {"
        + "  author: resolveSynthesisAuthor(matrix, session),"
        + '  spokesperson: resolveMemberCell("%s", matrix, session, %d, true),' % (SPOKESPERSON_ID, REGULAR_ROUNDS)
        + '  fallback: resolveMemberCell("%s", matrix, session, %d, true),' % (FALLBACK_ID, REGULAR_ROUNDS)
        + "};"
    )


def test_scene_synthesis_cell_belongs_to_the_member_who_actually_wrote_it():
    synthesis = _turn_cell(SYNTHESIS_ROUND, FALLBACK_ID, "done", SYNTHESIS_MESSAGE_ID)
    result = _run_scene_functions(
        SYNTHESIS_FN_NAMES,
        _resolve_synthesis_cells_script(_two_member_session(), _two_member_matrix(synthesis)),
    )
    assert result["author"] == FALLBACK_ID
    assert result["fallback"]["message_id"] == SYNTHESIS_MESSAGE_ID
    assert result["fallback"]["round"] == SYNTHESIS_ROUND
    assert result["spokesperson"]["round"] == REGULAR_ROUNDS
    assert result["spokesperson"]["message_id"] == "m3"


def test_scene_synthesis_cell_stays_on_spokesperson_while_no_synthesis_turn_exists():
    result = _run_scene_functions(
        SYNTHESIS_FN_NAMES,
        _resolve_synthesis_cells_script(_two_member_session(), _two_member_matrix(None)),
    )
    assert result["author"] == SPOKESPERSON_ID
    assert result["spokesperson"]["status"] == "pending"
    assert result["spokesperson"]["round"] == SYNTHESIS_ROUND
    assert result["fallback"]["round"] == REGULAR_ROUNDS


def _three_member_session() -> dict:
    return {
        "rounds": REGULAR_ROUNDS,
        "spokesperson": SPOKESPERSON_ID,
        "members": [SPOKESPERSON_ID, FALLBACK_ID, THIRD_MEMBER_ID],
    }


def _round_two_just_started_matrix() -> dict:
    return {
        "rounds": [
            {
                "round": 1,
                "cells": [
                    _turn_cell(1, SPOKESPERSON_ID, "done", "m1"),
                    _turn_cell(1, FALLBACK_ID, "done", "m2"),
                    _turn_cell(1, THIRD_MEMBER_ID, "done", "m3"),
                ],
            },
            {
                "round": 2,
                "cells": [
                    _turn_cell(2, SPOKESPERSON_ID, "running"),
                    _turn_cell(2, FALLBACK_ID, "pending"),
                    _turn_cell(2, THIRD_MEMBER_ID, "pending"),
                ],
            },
        ],
        "synthesis": None,
    }


def _find_speaker_script(session: dict, matrix: dict, last_message: dict) -> str:
    return (
        "const session = %s;" % json.dumps(session)
        + "const matrix = %s;" % json.dumps(matrix)
        + "const lastMessage = %s;" % json.dumps(last_message)
        + "return {"
        + "  currentRound: computeCurrentRound(matrix),"
        + "  atCurrentRound: findSpeakingMemberId({"
        + "    session, matrix, currentRound: computeCurrentRound(matrix),"
        + "    synthesisPhase: false, lastMessage, live: true }),"
        + "  atPreviousRound: findSpeakingMemberId({"
        + "    session, matrix, currentRound: 1,"
        + "    synthesisPhase: false, lastMessage, live: true }),"
        + "};"
    )


def test_scene_reports_no_speaker_when_last_message_predates_the_current_round():
    last_message = {"id": "m3", "author": THIRD_MEMBER_ID, "body": "onceki turun cevabi"}
    result = _run_scene_functions(
        ("isRoundStarted", "computeCurrentRound") + SPEAKER_FN_NAMES,
        _find_speaker_script(_three_member_session(), _round_two_just_started_matrix(), last_message),
        prelude_js=_scene_status_prelude(),
    )
    assert result["currentRound"] == REGULAR_ROUNDS
    assert result["atCurrentRound"] is None
    assert result["atPreviousRound"] == THIRD_MEMBER_ID


def test_scene_reports_the_speaker_whose_current_cell_holds_the_last_message():
    matrix = _round_two_just_started_matrix()
    matrix["rounds"][1]["cells"][1] = _turn_cell(2, FALLBACK_ID, "done", "m5")
    last_message = {"id": "m5", "author": FALLBACK_ID, "body": "guncel turun cevabi"}
    result = _run_scene_functions(
        ("isRoundStarted", "computeCurrentRound") + SPEAKER_FN_NAMES,
        _find_speaker_script(_three_member_session(), matrix, last_message),
        prelude_js=_scene_status_prelude(),
    )
    assert result["atCurrentRound"] == FALLBACK_ID


def test_scene_reports_no_speaker_once_the_session_is_no_longer_live():
    matrix = _round_two_just_started_matrix()
    matrix["rounds"][1]["cells"][1] = _turn_cell(2, FALLBACK_ID, "done", "m5")
    script = (
        "const session = %s;" % json.dumps(_three_member_session())
        + "const matrix = %s;" % json.dumps(matrix)
        + 'const lastMessage = { id: "m5", author: "%s", body: "kapanmis oturum" };' % FALLBACK_ID
        + "return findSpeakingMemberId({ session, matrix, currentRound: 2,"
        + "  synthesisPhase: false, lastMessage, live: false });"
    )
    result = _run_scene_functions(
        SPEAKER_FN_NAMES, script, prelude_js=_scene_status_prelude()
    )
    assert result is None


def test_scene_last_word_panel_is_gated_on_a_drawn_bubble_not_on_the_message_author():
    scene_jsx = _read_scene_jsx()
    assert "lastMessage.author : null" not in scene_jsx
    assert "function findSpeakingMemberId(" in scene_jsx
    assert "findSpeakingMemberId({" in scene_jsx
    assert "{speakingMemberId === null && <LastWordPanel" in scene_jsx


def test_scene_member_cell_resolution_never_reads_spokesperson_for_the_synthesis_owner():
    scene_jsx = _read_scene_jsx()
    start = scene_jsx.index("function resolveMemberCell(")
    end = scene_jsx.index("function findSpeakingMemberId(", start)
    resolve_body = scene_jsx[start:end]
    assert "session.spokesperson" not in resolve_body
    assert "resolveSynthesisAuthor(matrix, session)" in resolve_body
