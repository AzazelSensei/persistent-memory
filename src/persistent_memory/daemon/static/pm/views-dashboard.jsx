// persistent-memory — Dashboard (overview — the system's pulse).
(function () {
  const React = window.React;
  const { useMemo, useState, useEffect } = React;
  const { Icon, StatusPill, KindTag, fmtDate } = window.PMUI;

  if (!document.getElementById("pm-dash-css")) {
    const s = document.createElement("style");
    s.id = "pm-dash-css";
    s.textContent = `
.dash-grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--gap);margin-top:20px}
.dash-stat{padding:16px 18px;position:relative;overflow:hidden}
.dash-stat .l{font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--faint);display:flex;align-items:center;gap:7px}
.dash-stat .v{font-family:var(--font-mono);font-size:30px;font-weight:600;color:var(--txt-hi);margin-top:10px;letter-spacing:-1px}
.dash-stat .v.warn{color:var(--st-proposed)}
.dash-stat .v small{font-size:14px;color:var(--faint);font-weight:400;margin-left:4px}
.dash-stat .sub{font-size:11.5px;color:var(--dim);margin-top:5px}
.dash-spark{position:absolute;right:14px;top:16px;opacity:.5}
.dash-2col{display:grid;grid-template-columns:1.5fr 1fr;gap:var(--gap);margin-top:var(--gap)}
.dash-panel{padding:var(--pad)}
.dash-ph{display:flex;align-items:center;gap:9px;margin-bottom:14px}
.dash-ph .t{font-size:14px;font-weight:600;color:var(--txt-hi);white-space:nowrap}
.dash-ph .more{margin-left:auto;font-size:12px;color:var(--accent-ink);cursor:pointer;display:inline-flex;align-items:center;gap:4px}
.dash-cta{display:flex;align-items:center;gap:20px;padding:20px;background:linear-gradient(120deg,var(--accent-soft),transparent);border:1px solid var(--accent-line)}
.dash-cta .big{font-family:var(--font-mono);font-size:42px;font-weight:700;color:var(--st-proposed);line-height:1;letter-spacing:-2px}
.dash-cta .txt{flex:1}
.dash-cta .txt .t{font-size:15px;font-weight:600;color:var(--txt-hi)}
.dash-cta .txt .d{font-size:12.5px;color:var(--dim);margin-top:3px}
.dash-cta .acts{display:flex;flex-direction:column;gap:8px}
.dash-cta .acts .pm-btn{white-space:nowrap}
.dash-pbars{display:flex;flex-direction:column;gap:9px;margin-top:4px}
.dash-pbar{display:flex;align-items:center;gap:10px;font-size:12px}
.dash-pbar .nm{flex:0 0 130px;color:var(--txt);font-family:var(--font-mono);font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dash-pbar .track{flex:1;height:7px;border-radius:999px;background:var(--line2);overflow:hidden}
.dash-pbar .track i{display:block;height:100%;border-radius:999px;background:var(--st-proposed)}
.dash-pbar .n{flex:0 0 auto;font-family:var(--font-mono);color:var(--dim);font-size:11px}
.dash-feed{display:flex;flex-direction:column}
.dash-frow{display:flex;align-items:center;gap:12px;padding:11px 0;border-top:1px solid var(--line);cursor:pointer}
.dash-frow:first-child{border-top:0}
.dash-frow:hover .ft{color:var(--txt-hi)}
.dash-frow .fd{width:7px;height:7px;border-radius:50%;flex:0 0 auto}
.dash-frow .ft{flex:1;min-width:0;font-size:13px;color:var(--txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dash-frow .fm{flex:0 0 auto;font-family:var(--font-mono);font-size:10.5px;color:var(--faint);white-space:nowrap}
.dash-frow .pjn{flex:0 0 108px;font-family:var(--font-mono);font-size:10.5px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}
.dash-frow .fid{flex:0 0 auto;font-family:var(--font-mono);font-size:10.5px;color:var(--accent-ink)}
.dash-health{display:flex;flex-direction:column;gap:8px}
.dash-hrow{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-radius:var(--r-sm);border:1px solid var(--line);background:var(--panel-hi);cursor:pointer}
.dash-hrow:hover{border-color:var(--line2)}
.dash-hrow .hi{width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
.dash-hrow .htx{flex:1;min-width:0}
.dash-hrow .ht{font-size:12.5px;color:var(--txt-hi);font-weight:500;line-height:1.4}
.dash-hrow .hd{font-size:11px;color:var(--dim);margin-top:2px;line-height:1.4}
.dash-prj{display:flex;flex-direction:column}
.dash-prow{display:flex;align-items:center;gap:11px;padding:9px 0;border-top:1px solid var(--line);cursor:pointer;font-size:12.5px}
.dash-prow:first-child{border-top:0}
.dash-prow .pc{width:9px;height:9px;border-radius:3px;flex:0 0 auto}
.dash-prow .pn{flex:1;color:var(--txt);font-family:var(--font-mono);font-size:12px}
.dash-prow:hover .pn{color:var(--txt-hi)}
.dash-prow .pm{font-family:var(--font-mono);font-size:11px;color:var(--faint);white-space:nowrap}
`;
    document.head.appendChild(s);
  }

  const ST_COL = { proposed: "var(--st-proposed)", accepted: "var(--st-accepted)", superseded: "var(--st-superseded)", reverted: "var(--st-reverted)" };

  function Spark({ pts, color }) {
    const max = Math.max(...pts), min = Math.min(...pts);
    const w = 84, hh = 30;
    const d = pts.map((p, i) => `${(i / (pts.length - 1)) * w},${hh - ((p - min) / (max - min || 1)) * hh}`).join(" ");
    return (
      <svg className="dash-spark" width={w} height={hh} viewBox={`0 0 ${w} ${hh}`}>
        <polyline points={d} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    );
  }

  function Dashboard({ nav, statuses, enterQueue }) {
    const PM = window.PM;
    const s = PM.stats;
    const pendingByProject = useMemo(() => {
      const m = {};
      PM.all.forEach((r) => { if ((statuses[r.id] || r.status) === "proposed") m[r.project] = (m[r.project] || 0) + 1; });
      return Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 5);
    }, [statuses]);
    const maxPend = Math.max(...pendingByProject.map((p) => p[1]), 1);
    const livePending = PM.all.filter((r) => (statuses[r.id] || r.status) === "proposed").length;
    const reviewed = Object.keys(statuses).length;
    const [candCount, setCandCount] = useState(null);
    useEffect(() => {
      let active = true;
      window.PM_API && window.PM_API.fetchSupersessionCandidates().then((data) => {
        if (active) setCandCount((data.candidates || []).length);
      });
      return () => { active = false; };
    }, []);

    const hIcon = { conflict: ["link", "var(--st-reverted)"], stale: ["timeline", "var(--st-proposed)"], missing: ["session", "var(--st-superseded)"], duplicate: ["graph", "var(--violet)"] };

    return (
      <div className="pm-page fade-in">
        <div style={{ display: "flex", alignItems: "flex-end", gap: 14 }}>
          <div>
            <div className="pm-eyebrow">28 May 2026 · local · 127.0.0.1</div>
            <h1 className="pm-h" style={{ marginTop: 6, fontSize: 23 }}>Memory — overview</h1>
          </div>
        </div>

        <div className="dash-grid4">
          <div className="pm-card dash-stat">
            <div className="l"><Icon name="overview" size={14} /> Total memories</div>
            <div className="v">{s.total}</div>
            <div className="sub">{s.accepted} accepted · {s.superseded} superseded</div>
            <Spark pts={[120, 126, 131, 138, 144, 150, 157]} color="var(--accent)" />
          </div>
          <div className="pm-card dash-stat">
            <div className="l"><Icon name="queue" size={14} /> Pending review</div>
            <div className="v warn">{livePending}</div>
            <div className="sub">{reviewed > 0 ? `${reviewed} reviewed this session` : "none reviewed yet"}</div>
            <Spark pts={[44, 42, 45, 41, 40, 39, 38]} color="var(--st-proposed)" />
          </div>
          <div className="pm-card dash-stat">
            <div className="l"><Icon name="graph" size={14} /> Graph edges</div>
            <div className="v">{s.graphEdges}<small>/{s.graphNodes} nodes</small></div>
            <div className="sub">{s.clusters} clusters · 4 unexpected</div>
          </div>
          <div className="pm-card dash-stat">
            <div className="l"><Icon name="project" size={14} /> Projects</div>
            <div className="v">{s.projects}</div>
            <div className="sub">most active: persistent-memory</div>
          </div>
        </div>

        <div className="dash-2col">
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)" }}>
            <div className="pm-card dash-cta">
              <div className="big">{livePending}</div>
              <div className="txt">
                <div className="t">records pending review</div>
                <div className="d">Most were generated automatically. Review them quickly with the keyboard in queue mode, or bulk-process them in the list.</div>
                <div className="dash-pbars" style={{ marginTop: 14 }}>
                  {pendingByProject.map(([p, n]) => (
                    <div className="dash-pbar" key={p}>
                      <span className="nm">{p}</span>
                      <span className="track"><i style={{ width: (n / maxPend) * 100 + "%" }} /></span>
                      <span className="n">{n}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="acts">
                <button className="pm-btn accent" onClick={() => enterQueue("decision")}><Icon name="queue" size={15} /> Enter queue</button>
                <button className="pm-btn sm" onClick={() => nav("decisions")}>View list</button>
              </div>
            </div>

            <div className="pm-card dash-panel">
              <div className="dash-ph"><Icon name="timeline" size={16} style={{ color: "var(--accent-ink)" }} /><span className="t">Recent activity</span><span className="more" onClick={() => nav("timeline")}>Timeline <Icon name="chevR" size={13} /></span></div>
              <div className="dash-feed">
                {PM.activity.map((a, i) => (
                  <div className="dash-frow" key={i} onClick={() => nav("detail", { id: a.id })}>
                    <span className="fd" style={{ background: ST_COL[a.kind], boxShadow: "var(--glow) " + ST_COL[a.kind] }} />
                    <span className="fid">{a.id}</span>
                    <span className="ft">{a.title}</span>
                    <span className="pjn">{a.project}</span>
                    <span className="fm">{a.t.slice(5, 16)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)" }}>
            <div className="pm-card dash-panel">
              <div className="dash-ph"><Icon name="health" size={16} style={{ color: "var(--st-proposed)" }} /><span className="t">Health & audit</span><span className="more" onClick={() => nav("health")}>All <Icon name="chevR" size={13} /></span></div>
              <div className="dash-health">
                <div className="dash-hrow" onClick={() => nav("supersession")}>
                  <span className="hi" style={{ background: "color-mix(in srgb, var(--violet) 16%, transparent)", color: "var(--violet)" }}><Icon name="link" size={13} /></span>
                  <span className="htx">
                    <div className="ht">Supersession candidates: {candCount === null ? "…" : candCount}</div>
                    <div className="hd">Graph cross-cluster links — review, link or dismiss</div>
                  </span>
                </div>
                {PM.health.map((hh, i) => {
                  const [ic, col] = hIcon[hh.level];
                  return (
                    <div className="dash-hrow" key={i} onClick={() => hh.ids[0] && nav("detail", { id: hh.ids[0] })}>
                      <span className="hi" style={{ background: `color-mix(in srgb, ${col} 16%, transparent)`, color: col }}><Icon name={ic} size={13} /></span>
                      <span className="htx"><div className="ht">{hh.title}</div><div className="hd">{hh.detail}</div></span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="pm-card dash-panel">
              <div className="dash-ph"><Icon name="project" size={16} style={{ color: "var(--accent-ink)" }} /><span className="t">Active projects</span><span className="more" onClick={() => nav("projects")}>All <Icon name="chevR" size={13} /></span></div>
              <div className="dash-prj">
                {PM.projects.slice(0, 6).map((p) => (
                  <div className="dash-prow" key={p.id} onClick={() => nav("project", { id: p.id })}>
                    <span className="pc" style={{ background: p.color }} />
                    <span className="pn">{p.name}</span>
                    <span className="pm">{p.dec + p.les} records</span>
                    <span className="pm">{fmtDate(p.last)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
  window.PMDashboard = Dashboard;
})();
