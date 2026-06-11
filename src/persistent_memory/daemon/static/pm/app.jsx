// persistent-memory — App shell: sidebar nav, top KPI bar, routing, live
// approve/reject state, and Tweaks (theme/accent/density/font/radius).
(function () {
  const React = window.React;
  const { useState, useEffect, useCallback } = React;
  const { Icon } = window.PMUI;
  const { useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakColor, TweakToggle } = window;

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
    { sec: "Review" },
    { id: "overview", icon: "overview", label: "Overview" },
    { id: "decisions", icon: "decision", label: "Decisions", countKey: "dec" },
    { id: "lessons", icon: "lesson", label: "Lessons", countKey: "les" },
    { sec: "Explore" },
    { id: "graph", icon: "graph", label: "Graph" },
    { id: "projects", icon: "project", label: "Projects" },
    { id: "timeline", icon: "timeline", label: "Timeline" },
    { sec: "Tools" },
    { id: "search", icon: "search", label: "Search" },
    { id: "health", icon: "health", label: "Health & audit" },
    { id: "supersession", icon: "link", label: "Supersession" },
  ];

  function App() {
    const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
    const [view, setView] = useState("overview");
    const [params, setParams] = useState({});
    const [statuses, setStatuses] = useState({});
    const [collapsed, setCollapsed] = useState(false);
    const [toast, setToast] = useState(null);

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

    const activeNav = view === "queue" ? params.kind === "lesson" ? "lessons" : "decisions"
      : view === "project" ? "projects" : view === "detail" ? (PM.byId[params.id] && PM.byId[params.id].kind === "lesson" ? "lessons" : "decisions") : view;

    let content;
    if (view === "overview") content = <window.PMDashboard nav={nav} statuses={statuses} enterQueue={enterQueue} />;
    else if (view === "decisions") content = <window.PMList kind="decision" nav={nav} statuses={statuses} onAction={onAction} onBulk={onBulk} enterQueue={enterQueue} />;
    else if (view === "lessons") content = <window.PMList kind="lesson" nav={nav} statuses={statuses} onAction={onAction} onBulk={onBulk} enterQueue={enterQueue} />;
    else if (view === "queue") content = <window.PMQueue kind={params.kind} nav={nav} statuses={statuses} onAction={onAction} exitQueue={exitQueue} />;
    else if (view === "detail") content = <window.PMDetail rec={PM.byId[params.id]} nav={nav} onAction={onAction} liveStatus={statuses[params.id]} />;
    else if (view === "projects") content = <window.PMProjects nav={nav} statuses={statuses} />;
    else if (view === "project") content = <window.PMProjectDetail id={params.id} nav={nav} statuses={statuses} />;
    else if (view === "graph") content = <window.PMGraph nav={nav} statuses={statuses} />;
    else if (view === "timeline") content = <window.PMTimeline nav={nav} statuses={statuses} />;
    else if (view === "search") content = <window.PMSearch nav={nav} statuses={statuses} />;
    else if (view === "health") content = <window.PMHealth nav={nav} statuses={statuses} />;
    else if (view === "supersession") content = <window.PMCandidates nav={nav} />;

    return (
      <div className="pm-app" data-theme={t.theme} style={rootStyle}>
        <div className="pm-shell">
          <aside className={"pm-side" + (collapsed ? " collapsed" : "")}>
            <div className="pm-brand">
              <div className="pm-logo">pm</div>
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
                <span className="lbl">Review queue</span>
                {livePending > 0 && <span className="cnt warn">{livePending}</span>}
              </button>
            </div>
          </aside>

          <div className="pm-main">
            <header className="pm-top">
              <button className="pm-collapse" onClick={() => setCollapsed((c) => !c)} title="Sidebar"><Icon name="panel" size={17} /></button>
              <div className="pm-search" onClick={() => nav("search")}>
                <Icon name="search" size={15} />
                <input placeholder="Search memory — TR / EN…" readOnly value="" />
                <span className="kbd">/</span>
              </div>
              <div className="sp" />
              <div className="pm-kpis">
                <div className="pm-kpi"><span className="v">{PM.stats.total}</span><span className="l">total<br />memories</span></div>
                <div className="pm-kpi"><span className="v warn">{livePending}</span><span className="l">pending<br />review</span></div>
                <div className="pm-kpi"><span className="v">{PM.stats.graphEdges}</span><span className="l">graph<br />edges</span></div>
              </div>
            </header>
            <div className="pm-scroll">{content}</div>
          </div>
        </div>

        {toast && <div className="pm-toast">{toast}</div>}

        <TweaksPanel>
          <TweakSection label="Theme" />
          <TweakToggle label="Dark theme" value={t.theme === "dark"} onChange={(v) => setTweak("theme", v ? "dark" : "light")} />
          <TweakColor label="Accent color" value={t.accent}
            options={["#22d3ee", "#9d8cff", "#3ddc97", "#f5b13d", "#ff6b81"]}
            onChange={(v) => setTweak("accent", v)} />
          <TweakSection label="Layout" />
          <TweakRadio label="Density" value={t.density} options={["compact", "comfy"]} onChange={(v) => setTweak("density", v)} />
          <TweakRadio label="Corners" value={t.radius} options={["sharp", "normal", "soft"]} onChange={(v) => setTweak("radius", v)} />
          <TweakSection label="Typography" />
          <TweakRadio label="UI font" value={t.font} options={["Plex Sans", "Grotesk", "System"]} onChange={(v) => setTweak("font", v)} />
        </TweaksPanel>
      </div>
    );
  }

  window.PMApp = App;
})();
