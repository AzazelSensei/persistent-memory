import json
import re

from starlette.testclient import TestClient

from persistent_memory.daemon import dashboard_data
from persistent_memory.daemon.app import STATIC_DIR, create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.i18n import reset_lang_cache
from tests.daemon.jsx_runtime import extract_functions, run_extracted_functions

PM_STATIC = STATIC_DIR / "pm"
APP_JSX_PATH = PM_STATIC / "app.jsx"
COMPONENTS_JSX_PATH = PM_STATIC / "components.jsx"

LIVE_I18N_KEYS = [
    "ui.live.new_records",
    "ui.live.new_record_single",
    "ui.live.go_to_list",
    "ui.live.live",
    "ui.live.offline",
    "ui.live.reconnecting",
    "ui.live.stream_status",
]

LIVE_CONSTANT_RE = re.compile(r"^ {2}const (LIVE_[A-Z0-9_]+) = (.+);$", re.MULTILINE)
UNSAFE_KEYS_RE = re.compile(r"^ {2}const UNSAFE_RECORD_ID_KEYS = .+;$", re.MULTILINE)

STREAM_HOOK_FUNCTIONS = [
    "splitRecordId",
    "noteSeenRecordId",
    "readInitialWatermarks",
    "buildStreamUrl",
    "computeRetryDelay",
    "useLiveRecordStream",
]
RECORD_ENTRY_FUNCTIONS = ["buildLiveEntry", "applyLiveRecord"]

STREAM_PATH = "/api/stream/records"
EXPECTED_BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000]
CHANNEL_COUNT = 2


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _parse_i18n(body: str) -> dict:
    start = body.index("window.PM_I18N = ") + len("window.PM_I18N = ")
    end = body.index(";", start)
    return json.loads(body[start:end])


def _app_jsx() -> str:
    return APP_JSX_PATH.read_text(encoding="utf-8")


def _live_constants_js() -> str:
    """Inject the real LIVE_* constants so tests cannot drift from the source."""
    source = _app_jsx()
    lines = ["const %s = %s;" % (name, value) for name, value in LIVE_CONSTANT_RE.findall(source)]
    assert lines, "no LIVE_* constants found in app.jsx"
    return "\n".join(lines)


def _pm_registry_js() -> str:
    """Real pmById/registerPmRecord from components.jsx, not a test double."""
    components = COMPONENTS_JSX_PATH.read_text(encoding="utf-8")
    unsafe_keys = UNSAFE_KEYS_RE.search(components)
    assert unsafe_keys, "UNSAFE_RECORD_ID_KEYS not found in components.jsx"
    return "\n".join(
        [unsafe_keys.group(0), extract_functions(COMPONENTS_JSX_PATH, ["pmById", "registerPmRecord"])]
    )


_STREAM_HARNESS_JS = r"""
var openedUrls = [];
var sources = [];

function FakeEventSource(url) {
  this.url = url;
  this.isClosed = false;
  this.onopen = null;
  this.onerror = null;
  this.listeners = {};
  openedUrls.push(url);
  sources.push(this);
}
FakeEventSource.prototype.addEventListener = function (name, fn) {
  this.listeners[name] = this.listeners[name] || [];
  this.listeners[name].push(fn);
};
FakeEventSource.prototype.close = function () { this.isClosed = true; };
FakeEventSource.prototype.emitRaw = function (name, data) {
  (this.listeners[name] || []).forEach((fn) => fn({ data }));
};
FakeEventSource.prototype.emit = function (name, payload) {
  this.emitRaw(name, JSON.stringify(payload));
};
FakeEventSource.prototype.open = function () { this.onopen && this.onopen(); };
FakeEventSource.prototype.fail = function () { this.onerror && this.onerror(); };

globalThis.EventSource = FakeEventSource;
window.EventSource = FakeEventSource;

function liveSources() { return sources.filter((source) => !source.isClosed); }
function failAllOpenSources() { liveSources().forEach((source) => source.fail()); }

var timers = [];
var timerSeq = 0;
window.setTimeout = function (fn, delay) {
  timerSeq += 1;
  timers.push({ id: timerSeq, fn, delay, isCancelled: false, hasFired: false });
  return timerSeq;
};
window.clearTimeout = function (id) {
  timers.forEach((timer) => { if (timer.id === id) timer.isCancelled = true; });
};
function pendingTimers() { return timers.filter((t) => !t.isCancelled && !t.hasFired); }
function pendingDelays() { return pendingTimers().map((t) => t.delay); }
function runPendingTimers() {
  pendingTimers().forEach((timer) => { timer.hasFired = true; timer.fn(); });
}

var windowListeners = {};
var documentListeners = {};
function addListener(store, name, fn) { (store[name] = store[name] || []).push(fn); }
function removeListener(store, name, fn) {
  store[name] = (store[name] || []).filter((entry) => entry !== fn);
}
window.addEventListener = (name, fn) => addListener(windowListeners, name, fn);
window.removeEventListener = (name, fn) => removeListener(windowListeners, name, fn);
document.addEventListener = (name, fn) => addListener(documentListeners, name, fn);
document.removeEventListener = (name, fn) => removeListener(documentListeners, name, fn);
function fireWindowEvent(name) { (windowListeners[name] || []).slice().forEach((fn) => fn()); }
function fireDocumentEvent(name) { (documentListeners[name] || []).slice().forEach((fn) => fn()); }
function listenerCount() {
  return (windowListeners.online || []).length + (documentListeners.visibilitychange || []).length;
}

var hookSlots = [];
var cleanups = [];
var hookIndex = 0;

function useState(initial) {
  const index = hookIndex;
  hookIndex += 1;
  if (!hookSlots[index]) hookSlots[index] = { value: typeof initial === "function" ? initial() : initial };
  const slot = hookSlots[index];
  return [slot.value, (next) => { slot.value = typeof next === "function" ? next(slot.value) : next; }];
}
function useRef(initial) {
  const index = hookIndex;
  hookIndex += 1;
  if (!hookSlots[index]) hookSlots[index] = { current: initial === undefined ? null : initial };
  return hookSlots[index];
}
function useEffect(fn) {
  const cleanup = fn();
  if (typeof cleanup === "function") cleanups.push(cleanup);
}
function mountLiveHook(onRecord) {
  hookIndex = 0;
  return useLiveRecordStream(onRecord || function () {});
}
function unmountLiveHook() {
  cleanups.splice(0).forEach((cleanup) => cleanup());
}
function currentStatus() { return hookSlots[0].value; }
"""


def _run_stream_script(script_body: str, *, pm_records=()):
    pm_js = "window.PM = { all: %s };" % json.dumps([{"id": rec} for rec in pm_records])
    return run_extracted_functions(
        path=APP_JSX_PATH,
        names=STREAM_HOOK_FUNCTIONS,
        prelude_js="\n".join([_live_constants_js(), _STREAM_HARNESS_JS, pm_js]),
        script_body=script_body,
    )


_ENTRY_HARNESS_JS = r"""
var flashTimers = [];
globalThis.setTimeout = function (fn, delay) {
  flashTimers.push({ fn, delay });
  return flashTimers.length;
};

function seedPm(records) {
  const all = records.slice();
  window.PM = {
    all,
    decisions: all.filter((r) => r.kind === "decision"),
    lessons: all.filter((r) => r.kind === "lesson"),
    byId: Object.fromEntries(all.map((r) => [r.id, r])),
    stats: { total: all.length },
  };
  return window.PM;
}

function seededRecord(id, kind) {
  return {
    id,
    kind,
    title: id,
    status: "accepted",
    project: "alpha",
    branch: null,
    date: "2026-01-01",
    importance: 0.5,
    tags: [],
    source: { session: "s-old", sessionTitle: "alpha", passages: [] },
    relationships: { supersedes: null, supersededBy: null, related: [] },
  };
}

function liveEvent(id, type) {
  return { id, type, title: "Live " + id, project: "beta", date: "2026-07-25", status: "proposed" };
}
"""


def _run_entry_script(script_body: str):
    return run_extracted_functions(
        path=APP_JSX_PATH,
        names=RECORD_ENTRY_FUNCTIONS,
        prelude_js="\n".join([_live_constants_js(), _pm_registry_js(), _ENTRY_HARNESS_JS]),
        script_body=script_body,
    )


def _server_record_keys(tmp_path) -> set:
    decisions = tmp_path / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / "D-0001.md").write_text(
        "---\n"
        "id: D-0001\n"
        "type: decision\n"
        "status: proposed\n"
        "date: '2026-06-11'\n"
        "project: alpha\n"
        "provenance:\n"
        "  session: s-1\n"
        "  cwd: /tmp/work\n"
        "  agent: claude-sonnet-4-6\n"
        "tags: []\n"
        "supersedes: []\n"
        "superseded-by: []\n"
        "salience: 0.5\n"
        "---\n"
        "# Title\n\n## Context\nc\n\n## Decision\nd\n\n## Rationale\nr\n\n## Outcome\no\n",
        encoding="utf-8",
    )
    payload = dashboard_data.build_pm_payload(DaemonConfig(records_dir=tmp_path, projects_root=tmp_path))
    return set(payload["all"][0].keys())


def test_i18n_has_live_stream_keys_in_both_languages(tmp_path, monkeypatch):
    for lang in ("en", "tr"):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            for key in LIVE_I18N_KEYS:
                assert i18n_data.get(key), f"missing/empty {key} for lang={lang}"
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


def test_app_jsx_opens_event_source_for_records_stream():
    app_jsx = _app_jsx()
    assert "new EventSource(buildStreamUrl(" in app_jsx
    assert '"/api/stream/records"' in app_jsx
    assert 'addEventListener("record"' in app_jsx
    assert 'addEventListener("ping"' in app_jsx


def test_app_jsx_never_uses_dangerous_html():
    assert "dangerouslySetInnerHTML" not in _app_jsx()


def test_app_jsx_has_no_empty_catch_blocks():
    assert not re.search(r"catch\s*\([^)]*\)\s*\{\s*\}", _app_jsx())


def test_app_jsx_flash_set_used_for_new_rows():
    assert "window.__pmLiveFlash" in _app_jsx()


def test_views_list_marks_live_flash_rows():
    list_jsx = (PM_STATIC / "views-list.jsx").read_text(encoding="utf-8")
    assert "window.__pmLiveFlash" in list_jsx
    assert "l-row-new" in list_jsx


def test_styles_gate_row_flash_animation_on_reduced_motion():
    css = (PM_STATIC / "styles.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: no-preference" in css
    block_start = css.index("@media (prefers-reduced-motion: no-preference)")
    block_end = css.index("}", css.index("}", block_start) + 1) + 1
    reduced_block = css[block_start:block_end]
    assert ".l-row-new" in reduced_block
    assert "pmRowFlash" in css


# --- live badge wiring (a deleted onClick must fail these) ---------------------


def _live_indicator_usage() -> str:
    app_jsx = _app_jsx()
    start = app_jsx.index("<LiveIndicator")
    return app_jsx[start : app_jsx.index("/>", start)]


def _go_to_live_records_body() -> str:
    app_jsx = _app_jsx()
    start = app_jsx.index("const goToLiveRecords = useCallback(")
    return app_jsx[start : app_jsx.index("\n\n", start)]


def test_app_jsx_badge_accumulates_on_each_new_record():
    assert "setLiveBadge((n) => n + 1)" in _app_jsx()


def test_live_indicator_is_rendered_with_badge_click_handler():
    usage = _live_indicator_usage()
    assert "status={liveStatus}" in usage
    assert "badge={liveBadge}" in usage
    assert "onClick={goToLiveRecords}" in usage


def test_go_to_live_records_resets_badge_and_navigates_to_last_kind():
    body = _go_to_live_records_body()
    assert "setLiveBadge(0)" in body
    assert "nav(lastLiveKindRef.current" in body


def test_live_badge_button_invokes_the_on_click_prop():
    app_jsx = _app_jsx()
    start = app_jsx.index('<button className="pm-live-badge"')
    button = app_jsx[start : app_jsx.index(">", start)]
    assert "onClick={onClick}" in button


# --- accessible live/reconnecting/offline state (not colour-only) -------------


def _live_indicator_source() -> str:
    app_jsx = _app_jsx()
    start = app_jsx.index("function LiveIndicator")
    return app_jsx[start : app_jsx.index("const DENSITY", start)]


def test_live_indicator_exposes_status_as_polite_live_region():
    block = _live_indicator_source()
    assert 'role="status"' in block
    assert 'aria-live="polite"' in block


def test_live_indicator_renders_status_text_next_to_the_dot():
    block = _live_indicator_source()
    assert 'aria-hidden="true"' in block
    assert "{dotLabel}" in block
    assert 'ui.live.stream_status' in block


def test_live_indicator_badge_has_accessible_label():
    block = _live_indicator_source()
    assert "aria-label={" in block


def test_styles_define_screen_reader_only_and_visible_status_label():
    css = (PM_STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".pm-sr-only" in css
    assert ".pm-live-label" in css
    sr_block = css[css.index(".pm-sr-only") : css.index("}", css.index(".pm-sr-only"))]
    assert "position: absolute" in sr_block
    assert "clip: rect(0, 0, 0, 0)" in sr_block


# --- live record entry shape (behaviour, via node) ----------------------------


def test_live_entry_has_the_same_shape_as_a_server_built_record(tmp_path):
    result = _run_entry_script(
        """
        seedPm([seededRecord("D-0001", "decision")]);
        applyLiveRecord(liveEvent("D-0002", "decision"));
        const entry = window.PM.byId["D-0002"];
        return {
          keys: Object.keys(entry).sort(),
          sourceKeys: Object.keys(entry.source).sort(),
          relationshipKeys: Object.keys(entry.relationships).sort(),
        };
        """
    )
    assert set(result["keys"]) == _server_record_keys(tmp_path)
    assert result["sourceKeys"] == ["passages", "session", "sessionTitle"]
    assert result["relationshipKeys"] == ["related", "supersededBy", "supersedes"]


def test_live_entry_survives_detail_and_queue_field_reads():
    result = _run_entry_script(
        """
        seedPm([]);
        applyLiveRecord(liveEvent("L-0007", "lesson"));
        const rec = window.PM.byId["L-0007"];
        return {
          passages: (rec.source.passages || []).length,
          session: String(rec.source.session),
          passageCount: rec.source.passages.length,
          supersedes: rec.relationships.supersedes,
          supersededBy: rec.relationships.supersededBy,
          related: (rec.relationships.related || []).length,
          branch: rec.branch,
          tags: rec.tags.length,
          kind: rec.kind,
        };
        """
    )
    assert result == {
        "passages": 0,
        "session": "",
        "passageCount": 0,
        "supersedes": None,
        "supersededBy": None,
        "related": 0,
        "branch": None,
        "tags": 0,
        "kind": "lesson",
    }


def test_live_record_replaces_list_arrays_so_memoized_counts_refresh():
    result = _run_entry_script(
        """
        seedPm([seededRecord("D-0001", "decision"), seededRecord("L-0001", "lesson")]);
        const beforeAll = window.PM.all;
        const beforeDecisions = window.PM.decisions;
        const beforeLessons = window.PM.lessons;
        applyLiveRecord(liveEvent("D-0002", "decision"));
        return {
          isAllReplaced: window.PM.all !== beforeAll,
          isDecisionsReplaced: window.PM.decisions !== beforeDecisions,
          isLessonsKept: window.PM.lessons === beforeLessons,
          headId: window.PM.all[0].id,
          decisionsHeadId: window.PM.decisions[0].id,
          decisionsLength: window.PM.decisions.length,
          oldDecisionsLength: beforeDecisions.length,
          total: window.PM.stats.total,
        };
        """
    )
    assert result == {
        "isAllReplaced": True,
        "isDecisionsReplaced": True,
        "isLessonsKept": True,
        "headId": "D-0002",
        "decisionsHeadId": "D-0002",
        "decisionsLength": 2,
        "oldDecisionsLength": 1,
        "total": 3,
    }


def test_live_record_is_applied_once_per_id():
    result = _run_entry_script(
        """
        seedPm([]);
        const first = applyLiveRecord(liveEvent("D-0002", "decision"));
        const second = applyLiveRecord(liveEvent("D-0002", "decision"));
        return { first, second, length: window.PM.all.length, total: window.PM.stats.total, flash: flashTimers.length };
        """
    )
    assert result == {"first": True, "second": False, "length": 1, "total": 1, "flash": 1}


def test_live_record_flash_marker_expires_after_the_flash_window():
    result = _run_entry_script(
        """
        seedPm([]);
        applyLiveRecord(liveEvent("D-0002", "decision"));
        const marked = Array.from(window.__pmLiveFlash);
        flashTimers.forEach((timer) => timer.fn());
        return { marked, delay: flashTimers[0].delay, after: Array.from(window.__pmLiveFlash) };
        """
    )
    assert result == {"marked": ["D-0002"], "delay": 3000, "after": []}


# --- stream reconnect / watermark behaviour (behaviour, via node) -------------


def test_stream_opens_one_channel_per_record_prefix_with_its_own_since():
    result = _run_stream_script(
        """
        mountLiveHook();
        return { urls: openedUrls, status: currentStatus() };
        """,
        pm_records=["D-0009", "L-0004", "D-0011"],
    )
    assert result["urls"] == [
        STREAM_PATH + "?since=D-0011",
        STREAM_PATH + "?since=L-0004",
    ]


def test_stream_omits_since_when_no_record_is_known_yet():
    result = _run_stream_script(
        """
        mountLiveHook();
        return openedUrls;
        """
    )
    assert result == [STREAM_PATH, STREAM_PATH]


def test_stream_reconnect_resumes_from_the_last_received_record():
    result = _run_stream_script(
        """
        mountLiveHook();
        const initial = openedUrls.length;
        sources[0].emit("record", { id: "D-0012", type: "decision" });
        failAllOpenSources();
        runPendingTimers();
        return openedUrls.slice(initial);
        """,
        pm_records=["D-0009", "L-0004"],
    )
    assert result == [
        STREAM_PATH + "?since=D-0012",
        STREAM_PATH + "?since=L-0004",
    ]


def test_stream_retries_forever_with_capped_exponential_backoff():
    result = _run_stream_script(
        """
        mountLiveHook();
        const rounds = [];
        for (let i = 0; i < 6; i += 1) {
          failAllOpenSources();
          rounds.push({ delays: pendingDelays(), status: currentStatus() });
          runPendingTimers();
        }
        return { rounds, sourceCount: sources.length };
        """
    )
    delays = [round_["delays"] for round_ in result["rounds"]]
    assert delays == [[delay] * CHANNEL_COUNT for delay in EXPECTED_BACKOFF_MS]
    assert [round_["status"] for round_ in result["rounds"]] == [
        "reconnecting",
        "offline",
        "offline",
        "offline",
        "offline",
        "offline",
    ]
    assert result["sourceCount"] == CHANNEL_COUNT * 7


def test_stream_goes_back_to_live_when_a_channel_opens():
    result = _run_stream_script(
        """
        mountLiveHook();
        failAllOpenSources();
        const afterFailure = currentStatus();
        runPendingTimers();
        liveSources()[0].open();
        return { afterFailure, afterReopen: currentStatus() };
        """
    )
    assert result == {"afterFailure": "reconnecting", "afterReopen": "live"}


def test_stream_reconnects_immediately_when_the_network_comes_back():
    result = _run_stream_script(
        """
        mountLiveHook();
        for (let i = 0; i < 3; i += 1) { failAllOpenSources(); runPendingTimers(); }
        failAllOpenSources();
        const before = sources.length;
        const pendingBefore = pendingDelays().length;
        fireWindowEvent("online");
        return { before, pendingBefore, after: sources.length, pendingAfter: pendingDelays().length };
        """
    )
    assert result["pendingBefore"] == CHANNEL_COUNT
    assert result["after"] == result["before"] + CHANNEL_COUNT
    assert result["pendingAfter"] == 0


def test_stream_reconnects_immediately_when_the_tab_becomes_visible():
    result = _run_stream_script(
        """
        mountLiveHook();
        failAllOpenSources();
        const before = sources.length;
        document.hidden = false;
        fireDocumentEvent("visibilitychange");
        return { before, after: sources.length };
        """
    )
    assert result["after"] == result["before"] + CHANNEL_COUNT


def test_stream_cleanup_closes_sources_timers_and_listeners():
    result = _run_stream_script(
        """
        mountLiveHook();
        failAllOpenSources();
        const beforeUnmount = sources.length;
        const listenersBefore = listenerCount();
        unmountLiveHook();
        runPendingTimers();
        fireWindowEvent("online");
        fireDocumentEvent("visibilitychange");
        return {
          beforeUnmount,
          listenersBefore,
          after: sources.length,
          listenersAfter: listenerCount(),
          areAllClosed: sources.every((source) => source.isClosed),
        };
        """
    )
    assert result["listenersBefore"] == CHANNEL_COUNT
    assert result["listenersAfter"] == 0
    assert result["after"] == result["beforeUnmount"]
    assert result["areAllClosed"] is True


def test_stream_survives_a_malformed_record_event():
    result = _run_stream_script(
        """
        const seen = [];
        mountLiveHook((rec) => seen.push(rec.id));
        sources[0].emitRaw("record", "{not json");
        sources[0].emit("record", { id: "D-0013", type: "decision" });
        return { seen, status: currentStatus() };
        """
    )
    assert result == {"seen": ["D-0013"], "status": "live"}
