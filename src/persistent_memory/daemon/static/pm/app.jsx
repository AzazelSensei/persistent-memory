// persistent-memory — App shell: sidebar nav, top KPI bar, routing, live
// approve/reject state, and Tweaks (theme/accent/density/font/radius).
(function () {
  const React = window.React;
  const { useState, useEffect, useCallback, useRef } = React;
  const { Icon, pmById, registerPmRecord } = window.PMUI;
  const { useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakColor, TweakToggle } = window;

  const LIVE_STREAM_URL = "/api/stream/records";
  const LIVE_SINCE_PARAM = "since";
  const LIVE_STATUS_LIVE = "live";
  const LIVE_STATUS_RECONNECTING = "reconnecting";
  const LIVE_STATUS_OFFLINE = "offline";
  const LIVE_FLASH_MS = 3000;
  const LIVE_RETRY_BASE_MS = 1000;
  const LIVE_RETRY_MAX_MS = 30000;
  const LIVE_RETRY_FACTOR = 2;
  const LIVE_OFFLINE_AFTER_ATTEMPTS = 2;
  const LIVE_DECISION_PREFIX = "D";
  const LIVE_LESSON_PREFIX = "L";
  const LIVE_STREAM_PREFIXES = [LIVE_DECISION_PREFIX, LIVE_LESSON_PREFIX];
  const LIVE_ID_SEPARATOR = "-";
  const LIVE_STATUS_ALIASES = { "reverted-as-mistake": "reverted" };
  const LIVE_DEFAULT_STATUS = "proposed";

  function splitRecordId(id) {
    if (typeof id !== "string") return null;
    const at = id.indexOf(LIVE_ID_SEPARATOR);
    if (at <= 0) return null;
    const seq = parseInt(id.slice(at + 1), 10);
    if (!isFinite(seq)) return null;
    return { prefix: id.slice(0, at), seq };
  }

  function noteSeenRecordId(watermarks, id) {
    const parts = splitRecordId(id);
    if (!parts) return watermarks;
    const known = watermarks[parts.prefix];
    if (known && known.seq >= parts.seq) return watermarks;
    watermarks[parts.prefix] = { id, seq: parts.seq };
    return watermarks;
  }

  function readInitialWatermarks() {
    const watermarks = {};
    const PM = window.PM;
    const records = (PM && PM.all) || [];
    records.forEach((rec) => noteSeenRecordId(watermarks, rec && rec.id));
    return watermarks;
  }

  function buildStreamUrl(watermark) {
    if (!watermark || !watermark.id) return LIVE_STREAM_URL;
    return LIVE_STREAM_URL + "?" + LIVE_SINCE_PARAM + "=" + encodeURIComponent(watermark.id);
  }

  function computeRetryDelay(attempt) {
    if (attempt <= 1) return LIVE_RETRY_BASE_MS;
    const delay = LIVE_RETRY_BASE_MS * Math.pow(LIVE_RETRY_FACTOR, attempt - 1);
    return Math.min(delay, LIVE_RETRY_MAX_MS);
  }

  function buildLiveEntry(rec) {
    const kind = rec.type === "lesson" ? "lesson" : "decision";
    const project = rec.project || "";
    const status = rec.status || LIVE_DEFAULT_STATUS;
    return {
      id: rec.id,
      kind,
      title: rec.title || rec.id,
      project,
      branch: rec.branch || null,
      date: rec.date || "",
      status: LIVE_STATUS_ALIASES[status] || status,
      importance: 0,
      tags: [],
      source: { session: rec.session || "", sessionTitle: project, passages: [] },
      relationships: { supersedes: null, supersededBy: null, related: [] },
    };
  }

  function applyLiveRecord(rec) {
    const PM = window.PM;
    if (!PM || !rec || !rec.id || pmById(rec.id)) return false;
    const entry = buildLiveEntry(rec);
    PM.all = [entry].concat(PM.all);
    if (entry.kind === "lesson") PM.lessons = [entry].concat(PM.lessons);
    else PM.decisions = [entry].concat(PM.decisions);
    registerPmRecord(entry);
    PM.stats.total = (PM.stats.total || 0) + 1;
    window.__pmLiveFlash = window.__pmLiveFlash || new Set();
    window.__pmLiveFlash.add(rec.id);
    setTimeout(() => { window.__pmLiveFlash && window.__pmLiveFlash.delete(rec.id); }, LIVE_FLASH_MS);
    return true;
  }

  function useLiveRecordStream(onRecord) {
    const [status, setStatus] = useState(LIVE_STATUS_LIVE);
    const onRecordRef = useRef(onRecord);
    const watermarksRef = useRef(null);
    useEffect(() => { onRecordRef.current = onRecord; }, [onRecord]);

    useEffect(() => {
      if (typeof window.EventSource === "undefined") {
        setStatus(LIVE_STATUS_OFFLINE);
        return undefined;
      }

      const watermarks = watermarksRef.current || readInitialWatermarks();
      watermarksRef.current = watermarks;
      const channels = LIVE_STREAM_PREFIXES.map((prefix) => ({ prefix, source: null, timer: null, attempt: 0, isOpen: false }));
      let isCancelled = false;

      function closeChannelSource(channel) {
        if (!channel.source) return;
        channel.source.onopen = null;
        channel.source.onerror = null;
        channel.source.close();
        channel.source = null;
        channel.isOpen = false;
      }

      function syncStatus() {
        if (isCancelled) return;
        if (channels.some((channel) => channel.isOpen)) {
          setStatus(LIVE_STATUS_LIVE);
          return;
        }
        const attempts = channels.reduce((worst, channel) => Math.max(worst, channel.attempt), 0);
        setStatus(attempts >= LIVE_OFFLINE_AFTER_ATTEMPTS ? LIVE_STATUS_OFFLINE : LIVE_STATUS_RECONNECTING);
      }

      function handleRecordEvent(channel, event) {
        if (isCancelled) return;
        channel.attempt = 0;
        channel.isOpen = true;
        syncStatus();
        let rec = null;
        try {
          rec = JSON.parse(event.data);
        } catch (err) {
          console.warn("live stream: malformed record event", err);
          return;
        }
        noteSeenRecordId(watermarks, rec && rec.id);
        onRecordRef.current && onRecordRef.current(rec);
      }

      function scheduleReconnect(channel) {
        if (isCancelled || channel.timer) return;
        channel.attempt += 1;
        channel.timer = window.setTimeout(() => {
          channel.timer = null;
          openChannel(channel);
        }, computeRetryDelay(channel.attempt));
        syncStatus();
      }

      function openChannel(channel) {
        if (isCancelled) return;
        closeChannelSource(channel);
        const source = new EventSource(buildStreamUrl(watermarks[channel.prefix]));
        channel.source = source;
        source.onopen = () => {
          if (isCancelled) return;
          channel.attempt = 0;
          channel.isOpen = true;
          syncStatus();
        };
        source.addEventListener("record", (event) => handleRecordEvent(channel, event));
        source.addEventListener("ping", () => {});
        source.onerror = () => {
          if (isCancelled) return;
          closeChannelSource(channel);
          scheduleReconnect(channel);
        };
      }

      function reconnectNow() {
        if (isCancelled) return;
        channels.forEach((channel) => {
          if (channel.isOpen) return;
          window.clearTimeout(channel.timer);
          channel.timer = null;
          channel.attempt = 0;
          openChannel(channel);
        });
      }

      const onNetworkOnline = () => reconnectNow();
      const onVisibilityChange = () => { if (!document.hidden) reconnectNow(); };
      window.addEventListener("online", onNetworkOnline);
      document.addEventListener("visibilitychange", onVisibilityChange);
      channels.forEach(openChannel);

      return () => {
        isCancelled = true;
        window.removeEventListener("online", onNetworkOnline);
        document.removeEventListener("visibilitychange", onVisibilityChange);
        channels.forEach((channel) => {
          window.clearTimeout(channel.timer);
          channel.timer = null;
          closeChannelSource(channel);
        });
      };
    }, []);

    return status;
  }

  function LiveIndicator({ status, badge, onClick }) {
    const dotLabel = status === LIVE_STATUS_LIVE
      ? t("ui.live.live", "Live")
      : status === LIVE_STATUS_RECONNECTING
        ? t("ui.live.reconnecting", "Reconnecting…")
        : t("ui.live.offline", "Offline");
    const noun = badge === 1 ? t("ui.live.new_record_single", "new record") : t("ui.live.new_records", "new records");
    const streamLabel = t("ui.live.stream_status", "Record stream");
    const isLive = status === LIVE_STATUS_LIVE;
    return (
      <div className="pm-live" role="status" aria-live="polite">
        <span className={"pm-live-dot " + status} title={streamLabel + ": " + dotLabel} aria-hidden="true" />
        <span className="pm-sr-only">{streamLabel}: </span>
        <span className={isLive ? "pm-sr-only" : "pm-live-label"}>{dotLabel}</span>
        {badge > 0 && (
          <button className="pm-live-badge" onClick={onClick} title={t("ui.live.go_to_list", "Go to list")}
            aria-label={"+" + badge + " " + noun + " · " + t("ui.live.go_to_list", "Go to list")}>
            +{badge} {noun}
          </button>
        )}
      </div>
    );
  }

  const DENSITY = {
    compact: { "--row-py": "8px", "--pad": "14px", "--gap": "10px", "--fs": "13px" },
    comfy: { "--row-py": "14px", "--pad": "19px", "--gap": "15px", "--fs": "13.5px" },
  };
  const RADIUS = { sharp: "3px", normal: "8px", soft: "15px" };
  const FONTS = {
    "Plex Sans": '"IBM Plex Sans", system-ui, sans-serif',
    "Grotesk": '"Space Grotesk", system-ui, sans-serif',
    "System": 'system-ui, -apple-system, sans-serif',
  };

  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    theme: "dark",
    accent: "#9d8cff",
    density: "comfy",
    radius: "soft",
    font: "Grotesk",
  }/*EDITMODE-END*/;

  const NAV = [
    { sec: t("ui.nav.sec.review", "Review") },
    { id: "overview", icon: "overview", label: t("ui.nav.overview", "Overview") },
    { id: "decisions", icon: "decision", label: t("ui.nav.decisions", "Decisions"), countKey: "dec" },
    { id: "lessons", icon: "lesson", label: t("ui.nav.lessons", "Lessons"), countKey: "les" },
    { sec: t("ui.nav.sec.explore", "Explore") },
    { id: "graph", icon: "graph", label: t("ui.nav.graph", "Graph") },
    { id: "projects", icon: "project", label: t("ui.nav.projects", "Projects") },
    { id: "timeline", icon: "timeline", label: t("ui.nav.timeline", "Timeline") },
    { sec: t("ui.nav.sec.tools", "Tools") },
    { id: "search", icon: "search", label: t("ui.nav.search", "Search") },
    { id: "health", icon: "health", label: t("ui.nav.health", "Health & audit") },
    { id: "supersession", icon: "link", label: t("ui.nav.supersession", "Supersession") },
    { id: "agents", icon: "project", label: t("ui.nav.agents", "Agent rules & memory") },
    { id: "council", icon: "council", label: t("ui.nav.council", "Council") },
  ];

  function App() {
    const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
    const [view, setView] = useState("overview");
    const [params, setParams] = useState({});
    const [statuses, setStatuses] = useState({});
    const [collapsed, setCollapsed] = useState(false);
    const [toast, setToast] = useState(null);
    const [liveBadge, setLiveBadge] = useState(0);
    const [, bumpLiveTick] = useState(0);
    const lastLiveKindRef = useRef(null);

    const nav = useCallback((v, p = {}) => { setView(v); setParams(p); document.querySelector(".pm-scroll") && (document.querySelector(".pm-scroll").scrollTop = 0); }, []);
    useEffect(() => { window.__pmNav = nav; }, [nav]);

    const flash = (msg) => { setToast(msg); clearTimeout(window.__pmToast); window.__pmToast = setTimeout(() => setToast(null), 1900); };
    const onAction = useCallback((id, status) => {
      setStatuses((s) => ({ ...s, [id]: status }));
      flash(status === "accepted" ? "✓ Approved · " + id : "✕ Rejected · " + id);
      window.PM_API && window.PM_API.setStatus(id, status);
    }, []);
    const onBulk = useCallback((ids, status) => {
      setStatuses((s) => { const n = { ...s }; ids.forEach((i) => (n[i] = status)); return n; });
      flash((status === "accepted" ? "✓ " : "✕ ") + ids.length + " records updated");
      window.PM_API && ids.forEach((i) => window.PM_API.setStatus(i, status));
    }, []);

    const enterQueue = (kind) => nav("queue", { kind });
    const exitQueue = (kind) => nav(kind === "lesson" ? "lessons" : "decisions");

    const onLiveRecord = useCallback((rec) => {
      if (!applyLiveRecord(rec)) return;
      lastLiveKindRef.current = rec.type === "lesson" ? "lessons" : "decisions";
      setLiveBadge((n) => n + 1);
      bumpLiveTick((n) => n + 1);
    }, []);
    const liveStatus = useLiveRecordStream(onLiveRecord);
    const goToLiveRecords = useCallback(() => {
      setLiveBadge(0);
      nav(lastLiveKindRef.current || "decisions");
    }, [nav]);

    const PM = window.PM;
    const livePending = PM.all.filter((r) => (statuses[r.id] || r.status) === "proposed").length;

    // keyboard: "/" focus search
    useEffect(() => {
      const onKey = (e) => {
        if (e.key === "/" && view !== "queue" && !/input|textarea/i.test(e.target.tagName)) { e.preventDefault(); nav("search"); }
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [view]);

    const rootStyle = { ...DENSITY[t.density], "--accent": t.accent, "--r": RADIUS[t.radius], "--font-ui": FONTS[t.font] };

    const counts = {
      dec: PM.decisions.filter((r) => (statuses[r.id] || r.status) === "proposed").length,
      les: PM.lessons.filter((r) => (statuses[r.id] || r.status) === "proposed").length,
    };

    const detailRec = view === "detail" ? pmById(params.id) : null;
    const activeNav = view === "queue" ? params.kind === "lesson" ? "lessons" : "decisions"
      : view === "project" ? "projects" : view === "detail" ? (detailRec && detailRec.kind === "lesson" ? "lessons" : "decisions") : view;

    let content;
    if (view === "overview") content = <window.PMDashboard nav={nav} statuses={statuses} enterQueue={enterQueue} />;
    else if (view === "decisions") content = <window.PMList kind="decision" nav={nav} statuses={statuses} onAction={onAction} onBulk={onBulk} enterQueue={enterQueue} />;
    else if (view === "lessons") content = <window.PMList kind="lesson" nav={nav} statuses={statuses} onAction={onAction} onBulk={onBulk} enterQueue={enterQueue} />;
    else if (view === "queue") content = <window.PMQueue kind={params.kind} nav={nav} statuses={statuses} onAction={onAction} exitQueue={exitQueue} />;
    else if (view === "detail") content = <window.PMDetail rec={detailRec} nav={nav} onAction={onAction} liveStatus={statuses[params.id]} />;
    else if (view === "projects") content = <window.PMProjects nav={nav} statuses={statuses} />;
    else if (view === "project") content = <window.PMProjectDetail id={params.id} nav={nav} statuses={statuses} />;
    else if (view === "graph") content = <window.PMGraph nav={nav} statuses={statuses} />;
    else if (view === "timeline") content = <window.PMTimeline nav={nav} statuses={statuses} />;
    else if (view === "search") content = <window.PMSearch nav={nav} statuses={statuses} />;
    else if (view === "health") content = <window.PMHealth nav={nav} statuses={statuses} />;
    else if (view === "supersession") content = <window.PMCandidates nav={nav} />;
    else if (view === "agents") content = <window.PMAgents nav={nav} />;
    else if (view === "council") content = <window.PMCouncil nav={nav} />;

    return (
      <div className="pm-app" data-theme={t.theme} style={rootStyle}>
        <div className="pm-shell">
          <aside className={"pm-side" + (collapsed ? " collapsed" : "")}>
            <div className="pm-brand">
              <img className="pm-logo" src="/static/pm/logo.png" alt="persistent-memory" />
              <div className="nm">persistent-memory<small>second brain · local</small></div>
            </div>
            <nav className="pm-nav">
              {NAV.map((n, i) => n.sec
                ? <div key={"s" + i} className="pm-navsec">{n.sec}</div>
                : (
                  <button key={n.id} className={"pm-nav-item" + (activeNav === n.id ? " on" : "")} onClick={() => nav(n.id)} title={n.label}>
                    <span className="ico"><Icon name={n.icon} size={17} /></span>
                    <span className="lbl">{n.label}</span>
                    {n.countKey && counts[n.countKey] > 0 && <span className="cnt warn">{counts[n.countKey]}</span>}
                  </button>
                ))}
            </nav>
            <div className="pm-side-foot">
              <button className={"pm-nav-item" + (activeNav === "queue" ? " on" : "")} onClick={() => enterQueue("decision")}>
                <span className="ico"><Icon name="queue" size={17} /></span>
                <span className="lbl">{window.t("ui.nav.review_queue", "Review queue")}</span>
                {livePending > 0 && <span className="cnt warn">{livePending}</span>}
              </button>
            </div>
          </aside>

          <div className="pm-main">
            <header className="pm-top">
              <button className="pm-collapse" onClick={() => setCollapsed((c) => !c)} title="Sidebar"><Icon name="panel" size={17} /></button>
              <div className="pm-search" onClick={() => nav("search")}>
                <Icon name="search" size={15} />
                <input placeholder={window.t("ui.search.placeholder", "Search memory — TR / EN…")} readOnly value="" />
                <span className="kbd">/</span>
              </div>
              <div className="sp" />
              <LiveIndicator status={liveStatus} badge={liveBadge} onClick={goToLiveRecords} />
              <div className="pm-kpis">
                <div className="pm-kpi"><span className="v">{PM.stats.total}</span><span className="l">{window.t("ui.kpi.total_memories", "total memories")}</span></div>
                <div className="pm-kpi"><span className="v warn">{livePending}</span><span className="l">{window.t("ui.kpi.pending_review", "pending review")}</span></div>
                <div className="pm-kpi"><span className="v">{PM.stats.graphEdges}</span><span className="l">{window.t("ui.kpi.graph_edges", "graph edges")}</span></div>
              </div>
            </header>
            <div className="pm-scroll">{content}</div>
          </div>
        </div>

        {toast && <div className="pm-toast">{toast}</div>}

        <TweaksPanel>
          <TweakSection label={window.t("ui.tweaks.theme", "Theme")} />
          <TweakToggle label={window.t("ui.tweaks.dark_theme", "Dark theme")} value={t.theme === "dark"} onChange={(v) => setTweak("theme", v ? "dark" : "light")} />
          <TweakColor label={window.t("ui.tweaks.accent_color", "Accent color")} value={t.accent}
            options={["#22d3ee", "#9d8cff", "#3ddc97", "#f5b13d", "#ff6b81"]}
            onChange={(v) => setTweak("accent", v)} />
          <TweakSection label={window.t("ui.tweaks.layout", "Layout")} />
          <TweakRadio label={window.t("ui.tweaks.density", "Density")} value={t.density} options={["compact", "comfy"]} onChange={(v) => setTweak("density", v)} />
          <TweakRadio label={window.t("ui.tweaks.corners", "Corners")} value={t.radius} options={["sharp", "normal", "soft"]} onChange={(v) => setTweak("radius", v)} />
          <TweakSection label={window.t("ui.tweaks.typography", "Typography")} />
          <TweakRadio label={window.t("ui.tweaks.ui_font", "UI font")} value={t.font} options={["Plex Sans", "Grotesk", "System"]} onChange={(v) => setTweak("font", v)} />
        </TweaksPanel>
      </div>
    );
  }

  window.PMApp = App;
})();
