// persistent-memory — Projects overview + single-project memory.
(function () {
  const React = window.React;
  const { useMemo } = React;
  const { Icon, StatusPill, Importance, fmtDate } = window.PMUI;

  if (!document.getElementById("pm-pj-css")) {
    const s = document.createElement("style");
    s.id = "pm-pj-css";
    s.textContent = `
.pj-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(248px,1fr));gap:var(--gap);margin-top:20px}
.pj-card{padding:16px 17px;cursor:pointer;position:relative;overflow:hidden}
.pj-card:hover{border-color:var(--line2)}
.pj-card .bar{position:absolute;left:0;top:0;bottom:0;width:3px}
.pj-card .nm{font-family:var(--font-mono);font-size:14px;color:var(--txt-hi);font-weight:600;display:flex;align-items:center;gap:8px}
.pj-card .nm .dot{width:9px;height:9px;border-radius:3px;flex:0 0 auto}
.pj-stats{display:flex;gap:18px;margin-top:14px}
.pj-stats .st .v{font-family:var(--font-mono);font-size:19px;font-weight:600;color:var(--txt-hi)}
.pj-stats .st .l{font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.5px}
.pj-foot{display:flex;align-items:center;gap:8px;margin-top:14px;font-size:11.5px;color:var(--dim);font-family:var(--font-mono)}
.pj-foot .track{flex:1;height:5px;border-radius:999px;background:var(--line2);overflow:hidden}
.pj-foot .track i{display:block;height:100%;border-radius:999px}
.pj-d-head{display:flex;align-items:center;gap:16px;margin-top:8px}
.pj-d-head .dot{width:14px;height:14px;border-radius:5px;flex:0 0 auto}
.pj-d-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--gap);margin-top:20px}
`;
    document.head.appendChild(s);
  }

  function ProjectsView({ nav, statuses }) {
    const PM = window.PM;
    const maxConv = Math.max(...PM.projects.map((p) => p.conv));
    return (
      <div className="pm-page fade-in">
        <div className="pm-eyebrow">All projects</div>
        <h1 className="pm-h" style={{ marginTop: 6 }}>Projects <span style={{ color: "var(--faint)", fontWeight: 400, fontSize: 15 }}>· {PM.projects.length}</span></h1>
        <div className="pj-grid">
          {PM.projects.map((p) => (
            <div key={p.id} className="pm-card pj-card" onClick={() => nav("project", { id: p.id })}>
              <span className="bar" style={{ background: p.color }} />
              <div className="nm"><span className="dot" style={{ background: p.color }} />{p.name}</div>
              <div className="pj-stats">
                <div className="st"><div className="v">{p.dec}</div><div className="l">Decisions</div></div>
                <div className="st"><div className="v">{p.les}</div><div className="l">Lessons</div></div>
                <div className="st"><div className="v">{p.conv}</div><div className="l">Conversations</div></div>
              </div>
              <div className="pj-foot">
                <span className="track"><i style={{ width: (p.conv / maxConv) * 100 + "%", background: p.color }} /></span>
                <span>last {fmtDate(p.last)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  function ProjectDetail({ id, nav, statuses }) {
    const PM = window.PM;
    const p = PM.projects.find((x) => x.id === id) || PM.projects[0];
    const recs = useMemo(() => PM.all.filter((r) => r.project === p.id).sort((a, b) => b.date.localeCompare(a.date)), [p.id]);
    const pending = recs.filter((r) => (statuses[r.id] || r.status) === "proposed").length;
    const liveStatus = (r) => statuses[r.id] || r.status;

    return (
      <div className="pm-page fade-in">
        <button className="d-back" onClick={() => nav("projects")}><Icon name="arrowLeft" size={15} /> Projects</button>
        <div className="pj-d-head">
          <span className="dot" style={{ background: p.color }} />
          <div>
            <div className="pm-eyebrow">Project memory</div>
            <h1 className="pm-h pm-mono" style={{ marginTop: 4 }}>{p.name}</h1>
          </div>
        </div>
        <div className="pj-d-stats">
          {[["Decisions", p.dec], ["Lessons", p.les], ["Conversations", p.conv], ["Pending review", pending]].map(([l, v], i) => (
            <div key={l} className="pm-card dash-stat">
              <div className="l" style={{ textTransform: "uppercase", fontSize: 11, letterSpacing: ".7px", color: "var(--faint)" }}>{l}</div>
              <div className="v" style={{ fontFamily: "var(--font-mono)", fontSize: 26, fontWeight: 600, color: i === 3 && v > 0 ? "var(--st-proposed)" : "var(--txt-hi)", marginTop: 8 }}>{v}</div>
            </div>
          ))}
        </div>
        <div className="dash-ph" style={{ marginTop: 24, marginBottom: 12 }}>
          <Icon name="timeline" size={16} style={{ color: "var(--accent-ink)" }} /><span className="t" style={{ fontWeight: 600, color: "var(--txt-hi)" }}>Memory & activity</span>
          <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--faint)" }}>{recs.length} records</span>
        </div>
        <div className="l-list">
          {recs.map((r) => {
            const st = liveStatus(r);
            return (
              <div key={r.id} className={"l-row" + (st === "superseded" ? " sel-sup" : "")} onClick={() => nav("detail", { id: r.id })}>
                <span className="stat"><StatusPill status={st} /></span>
                <span className="rid pm-mono" style={{ fontSize: 11, color: "var(--faint)" }}>{r.id}</span>
                <span className="pm-kindtag" style={{ flex: "0 0 auto" }}>{r.kind === "lesson" ? "LESSON" : "DECISION"}</span>
                <span className="tt">{r.title}</span>
                <span className="imp"><Importance value={r.importance} w={60} showVal={false} /></span>
                <span className="dt">{fmtDate(r.date)}</span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  window.PMProjects = ProjectsView;
  window.PMProjectDetail = ProjectDetail;
})();
