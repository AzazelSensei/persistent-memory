// persistent-memory — List view (decisions/lessons) + Queue review mode.
(function () {
  const React = window.React;
  const { useState, useMemo, useEffect } = React;
  const { Icon, StatusPill, Importance, KindTag, fmtDate, renderRefs } = window.PMUI;

  if (!document.getElementById("pm-list-css")) {
    const s = document.createElement("style");
    s.id = "pm-list-css";
    s.textContent = `
.l-head{display:flex;align-items:flex-end;gap:16px;margin-bottom:18px}
.l-head>div:first-child{flex:0 0 auto}
.l-head .sp{flex:1}
.l-toolbar{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.l-chips{display:flex;gap:6px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);padding:3px}
.l-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:calc(var(--r-sm) - 1px);font-size:12px;color:var(--dim);cursor:pointer;border:0;background:none;font-family:inherit}
.l-chip .n{font-family:var(--font-mono);font-size:11px;opacity:.8}
.l-chip:hover{color:var(--txt)}
.l-chip.on{background:var(--accent-soft);color:var(--accent-ink)}
.l-chip .d{width:6px;height:6px;border-radius:50%}
.l-srch{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);padding:6px 11px;color:var(--dim);min-width:200px}
.l-srch:focus-within{border-color:var(--accent-line)}
.l-srch input{border:0;background:none;color:var(--txt);font-family:inherit;font-size:12.5px;outline:none;width:100%}
.l-sel{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);color:var(--txt);font-family:inherit;font-size:12.5px;padding:7px 9px;cursor:pointer}
.l-list{border:1px solid var(--line);border-radius:var(--r);overflow:hidden;background:var(--panel)}
.l-row{display:flex;align-items:center;gap:14px;padding:var(--row-py) 16px;border-bottom:1px solid var(--line);cursor:pointer;position:relative}
.l-row:last-child{border-bottom:0}
.l-row:hover{background:var(--panel-hi)}
.l-row .stat{flex:0 0 92px}
.l-row .tt{flex:1;min-width:0;font-size:13.5px;color:var(--txt-hi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.l-row.sel-sup .tt{text-decoration:line-through;color:var(--dim)}
.l-row .pj{flex:0 0 auto;font-family:var(--font-mono);font-size:11px;color:var(--dim);background:var(--panel-hi);border:1px solid var(--line);padding:2px 8px;border-radius:999px}
.l-row .rid{flex:0 0 auto;font-family:var(--font-mono);font-size:11px;color:var(--faint)}
.l-row .imp{flex:0 0 auto}
.l-row .dt{flex:0 0 46px;text-align:right;font-family:var(--font-mono);font-size:11px;color:var(--faint)}
.l-qa{flex:0 0 auto;display:flex;gap:6px;opacity:0;transition:opacity .12s}
.l-row:hover .l-qa{opacity:1}
.l-qa button{width:30px;height:30px;border-radius:var(--r-sm);border:1px solid var(--line2);background:var(--panel);display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--dim)}
.l-qa button.ok:hover{color:var(--st-accepted);border-color:var(--st-accepted)}
.l-qa button.no:hover{color:var(--st-reverted);border-color:var(--st-reverted)}
.l-count{font-family:var(--font-mono);font-size:12px;color:var(--faint);white-space:nowrap}
.l-cb{width:15px;height:15px;border-radius:4px;border:1.5px solid var(--line2);flex:0 0 auto;display:flex;align-items:center;justify-content:center;color:var(--accent-ink);cursor:pointer}
.l-cb.on{background:var(--accent);border-color:var(--accent);color:#04141a}
.l-bulk{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--accent-soft);border:1px solid var(--accent-line);border-radius:var(--r-sm);margin-bottom:12px;font-size:13px;color:var(--accent-ink)}

/* queue */
.q-top{display:flex;align-items:center;gap:14px;margin-bottom:18px}
.q-prog{flex:1;height:6px;border-radius:999px;background:var(--line2);overflow:hidden}
.q-prog i{display:block;height:100%;background:var(--accent);transition:width .25s}
.q-card{max-width:780px;margin:0 auto;padding:30px 34px}
.q-card .qhead{display:flex;align-items:center;gap:12px;margin-bottom:6px}
.q-card h2{font-size:24px;line-height:1.3;color:var(--txt-hi);font-weight:600;letter-spacing:-0.3px;margin:14px 0 0;max-width:30ch}
.q-tags{display:flex;gap:7px;margin-top:14px;flex-wrap:wrap}
.q-secs{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:24px}
.q-sec{padding:0}
.q-sec .sh{font-size:11px;font-weight:600;color:var(--accent-ink);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}
.q-sec p{margin:0;font-size:13.5px;line-height:1.62;color:var(--txt)}
.q-src{margin-top:24px;padding-top:18px;border-top:1px solid var(--line);display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--dim)}
.q-src .dt{width:8px;height:8px;border-radius:50%;background:var(--st-accepted);flex:0 0 auto}
.q-actions{display:flex;justify-content:center;gap:12px;margin-top:26px}
.q-actions .pm-btn{min-width:130px;padding:11px 16px}
.q-hint{text-align:center;color:var(--faint);font-size:12px;margin-top:16px;display:flex;gap:18px;justify-content:center}
.q-hint span{display:inline-flex;align-items:center;gap:6px}
.q-empty{max-width:520px;margin:60px auto;text-align:center}
.q-empty .big{width:60px;height:60px;border-radius:16px;background:var(--accent-soft);color:var(--accent-ink);display:flex;align-items:center;justify-content:center;margin:0 auto 18px}
`;
    document.head.appendChild(s);
  }

  const STAT_ORDER = ["proposed", "accepted", "superseded", "reverted"];
  const STAT_COL = { proposed: "var(--st-proposed)", accepted: "var(--st-accepted)", superseded: "var(--st-superseded)", reverted: "var(--st-reverted)" };

  function ListView({ kind, nav, statuses, onAction, onBulk, enterQueue }) {
    const PM = window.PM;
    const base = kind === "lesson" ? PM.lessons : PM.decisions;
    const [statFilter, setStatFilter] = useState("all");
    const [project, setProject] = useState("all");
    const [q, setQ] = useState("");
    const [selected, setSelected] = useState({});

    const liveStatus = (r) => statuses[r.id] || r.status;
    const counts = useMemo(() => {
      const c = { all: base.length, proposed: 0, accepted: 0, superseded: 0, reverted: 0 };
      base.forEach((r) => c[liveStatus(r)]++);
      return c;
    }, [base, statuses]);

    const rows = base.filter((r) => {
      if (statFilter !== "all" && liveStatus(r) !== statFilter) return false;
      if (project !== "all" && r.project !== project) return false;
      if (q && !(r.title.toLowerCase().includes(q.toLowerCase()) || r.id.toLowerCase().includes(q.toLowerCase()) || r.tags.join(" ").includes(q.toLowerCase()))) return false;
      return true;
    });

    const selIds = Object.keys(selected).filter((k) => selected[k]);
    const toggleSel = (id, e) => { e.stopPropagation(); setSelected((s) => ({ ...s, [id]: !s[id] })); };

    return (
      <div className="pm-page fade-in">
        <div className="l-head">
          <div>
            <div className="pm-eyebrow">{kind === "lesson" ? "Lesson & mistake records" : "Decision records"}</div>
            <h1 className="pm-h" style={{ marginTop: 6 }}>{kind === "lesson" ? "Lessons" : "Decisions"}</h1>
          </div>
          <div className="sp" />
          <span className="l-count">{rows.length} / {base.length} records</span>
          <button className="pm-btn accent sm" onClick={() => enterQueue(kind)}>
            <Icon name="queue" size={15} /> Queue mode
          </button>
        </div>

        <div className="l-toolbar">
          <div className="l-chips">
            <button className={"l-chip" + (statFilter === "all" ? " on" : "")} onClick={() => setStatFilter("all")}>All <span className="n">{counts.all}</span></button>
            {STAT_ORDER.map((st) => (
              <button key={st} className={"l-chip" + (statFilter === st ? " on" : "")} onClick={() => setStatFilter(st)}>
                <span className="d" style={{ background: STAT_COL[st] }} />{st} <span className="n">{counts[st]}</span>
              </button>
            ))}
          </div>
          <select className="l-sel" value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="all">all projects</option>
            {PM.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <div className="l-srch">
            <Icon name="search" size={14} />
            <input placeholder="title, id, tag…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>

        {selIds.length > 0 && (
          <div className="l-bulk">
            <Icon name="decision" size={15} />
            <b>{selIds.length}</b> records selected
            <div style={{ flex: 1 }} />
            <button className="pm-btn ok sm" onClick={() => { onBulk(selIds, "accepted"); setSelected({}); }}><Icon name="decision" size={14} /> Accept selected</button>
            <button className="pm-btn no sm" onClick={() => { onBulk(selIds, "reverted"); setSelected({}); }}><Icon name="close" size={14} /> Reject selected</button>
            <button className="pm-btn ghost sm" onClick={() => setSelected({})}>Clear</button>
          </div>
        )}

        <div className="l-list">
          {rows.length === 0 && <div className="pm-empty">No records match the filter.</div>}
          {rows.map((r) => {
            const st = liveStatus(r);
            return (
              <div key={r.id} className={"l-row" + (st === "superseded" ? " sel-sup" : "")} onClick={() => nav("detail", { id: r.id })}>
                <span className={"l-cb" + (selected[r.id] ? " on" : "")} onClick={(e) => toggleSel(r.id, e)}>
                  {selected[r.id] && <Icon name="decision" size={11} sw={2.4} />}
                </span>
                <span className="stat"><StatusPill status={st} /></span>
                <span className="rid">{r.id}</span>
                <span className="tt">{r.title}</span>
                <span className="imp"><Importance value={r.importance} w={64} showVal={false} /></span>
                <span className="pj">{r.project}</span>
                <span className="dt">{fmtDate(r.date)}</span>
                {st === "proposed" ? (
                  <span className="l-qa">
                    <button className="ok" title="Approve" onClick={(e) => { e.stopPropagation(); onAction(r.id, "accepted"); }}><Icon name="decision" size={15} /></button>
                    <button className="no" title="Reject" onClick={(e) => { e.stopPropagation(); onAction(r.id, "reverted"); }}><Icon name="close" size={15} /></button>
                  </span>
                ) : <span className="l-qa" style={{ width: 66 }} />}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  function QueueView({ kind, nav, statuses, onAction, exitQueue }) {
    const PM = window.PM;
    const base = kind === "lesson" ? PM.lessons : PM.decisions;
    const queue = useMemo(() => base.filter((r) => (statuses[r.id] || r.status) === "proposed"), []);
    const [idx, setIdx] = useState(0);
    const [done, setDone] = useState(0);

    const rec = queue[idx];

    const advance = () => setIdx((i) => i + 1);
    const act = (status) => { if (!rec) return; onAction(rec.id, status); setDone((d) => d + 1); advance(); };

    useEffect(() => {
      const onKey = (e) => {
        if (e.key === "a" || e.key === "A") act("accepted");
        else if (e.key === "r" || e.key === "R") act("reverted");
        else if (e.key === "j" || e.key === "J" || e.key === "ArrowRight") advance();
        else if (e.key === "Escape") exitQueue(kind);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [rec]);

    if (!rec) {
      return (
        <div className="pm-page fade-in">
          <div className="q-empty pm-card" style={{ padding: 44 }}>
            <div className="big"><Icon name="decision" size={28} /></div>
            <h2 className="pm-h" style={{ fontSize: 19 }}>Queue complete</h2>
            <p className="pm-sub" style={{ marginBottom: 22 }}><b style={{ color: "var(--txt-hi)" }}>{done}</b> records reviewed this session. No pending {kind === "lesson" ? "lessons" : "decisions"} left.</p>
            <button className="pm-btn accent" onClick={() => exitQueue(kind)}>Back to list</button>
          </div>
        </div>
      );
    }

    return (
      <div className="pm-page fade-in">
        <div className="q-top">
          <button className="pm-btn ghost sm" onClick={() => exitQueue(kind)}><Icon name="arrowLeft" size={14} /> Back to list</button>
          <div className="q-prog"><i style={{ width: ((idx) / queue.length) * 100 + "%" }} /></div>
          <span className="l-count">{idx + 1} / {queue.length} · {done} reviewed</span>
        </div>
        <div className="pm-card q-card" key={rec.id}>
          <div className="qhead">
            <StatusPill status="proposed" />
            <KindTag kind={rec.kind} />
            <span className="d-id pm-mono" style={{ fontSize: 12, color: "var(--faint)" }}>{rec.id} · {rec.project}</span>
            <div style={{ flex: 1 }} />
            <Importance value={rec.importance} w={80} />
          </div>
          <h2>{rec.title}</h2>
          <div className="q-tags">{rec.tags.map((t) => <span className="pm-tag" key={t}>{t}</span>)}</div>
          <div className="q-secs">
            {rec.sections.map((sec) => (
              <div className="q-sec" key={sec.en}>
                <div className="sh">{sec.label}</div>
                <p>{renderRefs(sec.text, nav)}</p>
              </div>
            ))}
          </div>
          <div className="q-src">
            <span className="dt" />
            <span className="pm-mono" style={{ color: "var(--txt)" }}>{rec.source.session}</span>
            <span>· {rec.source.passages.length} source passages</span>
            <div style={{ flex: 1 }} />
            <button className="pm-btn ghost sm" onClick={() => nav("detail", { id: rec.id })}>Full detail →</button>
          </div>
        </div>
        <div className="q-actions">
          <button className="pm-btn no" onClick={() => act("reverted")}><Icon name="close" size={16} /> Reject</button>
          <button className="pm-btn ghost" onClick={advance}><Icon name="arrowRight" size={16} /> Skip</button>
          <button className="pm-btn ok" onClick={() => act("accepted")}><Icon name="decision" size={16} /> Approve</button>
        </div>
        <div className="q-hint">
          <span><span className="pm-kbd">A</span> approve</span>
          <span><span className="pm-kbd">R</span> reject</span>
          <span><span className="pm-kbd">J</span> skip</span>
          <span><span className="pm-kbd">Esc</span> exit</span>
        </div>
      </div>
    );
  }

  window.PMList = ListView;
  window.PMQueue = QueueView;
})();
