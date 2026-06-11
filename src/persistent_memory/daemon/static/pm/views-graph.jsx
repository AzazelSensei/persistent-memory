// persistent-memory — Graph view. Cross-project knowledge graph:
// cluster-laid-out nodes, edges, "unexpected" cross-cluster links,
// hover-to-highlight neighbourhood, click node -> record.
(function () {
  const React = window.React;
  const { useState, useMemo } = React;
  const { Icon } = window.PMUI;

  if (!document.getElementById("pm-graph-css")) {
    const s = document.createElement("style");
    s.id = "pm-graph-css";
    s.textContent = `
.gr-wrap{display:flex;gap:var(--gap);margin-top:16px;align-items:stretch}
.gr-canvas{flex:1;min-width:0;border:1px solid var(--line);border-radius:var(--r);background:
  radial-gradient(circle at 30% 20%, color-mix(in srgb,var(--accent) 6%,var(--panel)), var(--panel) 60%);
  overflow:hidden;position:relative}
.gr-canvas svg{display:block;width:100%;height:560px}
.gr-side{width:288px;flex:0 0 288px;display:flex;flex-direction:column;gap:var(--gap)}
.gr-panel{padding:14px 16px}
.gr-ph{font-size:10.5px;text-transform:uppercase;letter-spacing:1px;color:var(--faint);margin-bottom:11px;display:flex;align-items:center;gap:7px;white-space:nowrap}
.gr-leg{display:flex;flex-direction:column;gap:3px}
.gr-legrow{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:var(--r-sm);cursor:pointer;font-size:12.5px;color:var(--txt);white-space:nowrap}
.gr-legrow:hover{background:var(--panel-hi)}
.gr-legrow.off{opacity:.4}
.gr-legrow .sw{width:11px;height:11px;border-radius:4px;flex:0 0 auto}
.gr-legrow .n{margin-left:auto;font-family:var(--font-mono);font-size:11px;color:var(--faint)}
.gr-unexp{display:flex;flex-direction:column;gap:8px}
.gr-urow{padding:9px 11px;border-radius:var(--r-sm);border:1px solid var(--accent-line);background:var(--accent-soft);cursor:pointer}
.gr-urow:hover{filter:brightness(1.05)}
.gr-urow .top{display:flex;align-items:center;gap:7px;font-family:var(--font-mono);font-size:11px;color:var(--accent-ink);margin-bottom:4px}
.gr-urow .conf{margin-left:auto;color:var(--dim)}
.gr-urow .dd{font-size:11.5px;color:var(--txt);line-height:1.4}
.gr-tip{position:absolute;pointer-events:none;background:var(--bg2);border:1px solid var(--line2);border-radius:var(--r-sm);
  padding:8px 11px;font-size:12px;color:var(--txt-hi);max-width:240px;box-shadow:var(--shadow);z-index:5}
.gr-tip .id{font-family:var(--font-mono);font-size:10.5px;color:var(--accent-ink);margin-bottom:3px}
.gr-tip .pj{font-family:var(--font-mono);font-size:10px;color:var(--faint);margin-top:4px}
.gr-node{cursor:pointer}
.gr-node text{pointer-events:none;font-family:var(--font-mono)}
.gr-stat{display:flex;gap:16px;padding:10px 16px;border-top:1px solid var(--line);font-size:11.5px;color:var(--dim)}
.gr-stat span{white-space:nowrap}
.gr-stat b{font-family:var(--font-mono);color:var(--txt-hi)}
`;
    document.head.appendChild(s);
  }

  const W = 1000, H = 560;

  function GraphView({ nav, statuses }) {
    const PM = window.PM;
    const [hover, setHover] = useState(null);
    const [tip, setTip] = useState(null);
    const [activeCluster, setActiveCluster] = useState(null);
    const [showUnexp, setShowUnexp] = useState(true);

    const positions = useMemo(() => {
      const pos = {};
      const cl = PM.clusters;
      const cx0 = W / 2, cy0 = H / 2, rx = 330, ry = 195;
      const byCluster = {};
      PM.nodes.forEach((n) => { (byCluster[n.cluster] = byCluster[n.cluster] || []).push(n); });
      cl.forEach((c, ci) => {
        const ang = (ci / cl.length) * Math.PI * 2 - Math.PI / 2;
        const cx = cx0 + Math.cos(ang) * rx;
        const cy = cy0 + Math.sin(ang) * ry;
        const nodes = byCluster[c.id] || [];
        const clusterR = 34 + 11 * Math.sqrt(nodes.length);
        nodes.forEach((n, k) => {
          const r = clusterR * Math.sqrt((k + 0.4) / nodes.length);
          const theta = k * 2.399963;
          pos[n.id] = { x: cx + r * Math.cos(theta), y: cy + r * Math.sin(theta), cluster: c.id, cx, cy };
        });
      });
      return pos;
    }, []);

    const neighbors = useMemo(() => {
      const m = {};
      PM.edges.forEach((e) => {
        (m[e.from] = m[e.from] || new Set()).add(e.to);
        (m[e.to] = m[e.to] || new Set()).add(e.from);
      });
      return m;
    }, []);

    const clusterColor = (id) => (PM.clusters.find((c) => c.id === id) || {}).color || "var(--accent)";
    const nodeDim = (n) => {
      if (activeCluster && n.cluster !== activeCluster) return true;
      if (hover && hover !== n.id && !(neighbors[hover] && neighbors[hover].has(n.id))) return true;
      return false;
    };
    const edgeActive = (e) => hover && (e.from === hover || e.to === hover);

    const unexpected = PM.edges.filter((e) => e.unexpected);

    return (
      <div className="pm-page fade-in">
        <div style={{ display: "flex", alignItems: "flex-end", gap: 14 }}>
          <div style={{ flexShrink: 0 }}>
            <div className="pm-eyebrow">Cross-project knowledge graph</div>
            <h1 className="pm-h" style={{ marginTop: 6 }}>Graph</h1>
          </div>
          <div style={{ flex: 1 }} />
          <button className={"pm-btn sm" + (showUnexp ? " accent" : "")} onClick={() => setShowUnexp((v) => !v)}>
            <Icon name="spark" size={14} /> Unexpected links
          </button>
        </div>

        <div className="gr-wrap">
          <div className="gr-canvas" onMouseLeave={() => { setHover(null); setTip(null); }}>
            <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
              {/* cluster halos */}
              {PM.clusters.map((c, ci) => {
                const any = PM.nodes.find((n) => n.cluster === c.id);
                if (!any) return null;
                const p = positions[any.id];
                if (!p) return null;
                const dim = activeCluster && activeCluster !== c.id;
                return <circle key={c.id} cx={p.cx} cy={p.cy} r={78} fill={c.color} opacity={dim ? 0.02 : 0.06} />;
              })}
              {/* edges */}
              {PM.edges.map((e, i) => {
                const a = positions[e.from], b = positions[e.to];
                if (!a || !b) return null;
                if (e.unexpected && !showUnexp) return null;
                const act = edgeActive(e);
                const isUn = e.unexpected;
                const dimmed = (activeCluster && (positions[e.from].cluster !== activeCluster && positions[e.to].cluster !== activeCluster)) || (hover && !act);
                return (
                  <g key={i}>
                    <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={isUn ? "var(--accent)" : (act ? "var(--accent)" : "var(--line2)")}
                      strokeWidth={act ? 2 : isUn ? 1.6 : 1}
                      strokeDasharray={isUn ? "5 4" : "0"}
                      opacity={dimmed ? 0.12 : isUn ? 0.7 : 0.5} />
                    {isUn && act && (
                      <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} textAnchor="middle" fontSize="9" fill="var(--accent-ink)" fontFamily="var(--font-mono)">{e.conf.toFixed(2)}</text>
                    )}
                  </g>
                );
              })}
              {/* nodes */}
              {PM.nodes.map((n) => {
                const p = positions[n.id];
                if (!p) return null;
                const st = statuses[n.id] || n.status;
                const col = clusterColor(n.cluster);
                const r = 7 + n.imp * 9;
                const dim = nodeDim(n);
                const isHover = hover === n.id;
                const faded = st === "superseded" || st === "reverted";
                return (
                  <g key={n.id} className="gr-node"
                    onMouseEnter={(ev) => { setHover(n.id); }}
                    onMouseMove={(ev) => {
                      const rect = ev.currentTarget.ownerSVGElement.parentElement.getBoundingClientRect();
                      setTip({ n, x: (p.x / W) * rect.width + 14, y: (p.y / H) * rect.height + 10 });
                    }}
                    onClick={() => nav("detail", { id: n.id })}
                    opacity={dim ? 0.22 : 1}>
                    {isHover && <circle cx={p.x} cy={p.y} r={r + 6} fill="none" stroke={col} strokeWidth="1.5" opacity="0.5" />}
                    <circle cx={p.x} cy={p.y} r={r}
                      fill={`color-mix(in srgb, ${col} ${faded ? 14 : 30}%, var(--panel))`}
                      stroke={st === "reverted" ? "var(--st-reverted)" : col}
                      strokeWidth={isHover ? 2.4 : 1.6}
                      strokeDasharray={st === "superseded" ? "3 2" : "0"} />
                    {r > 11 && <text x={p.x} y={p.y + 3} textAnchor="middle" fontSize="8.5" fill={col} fontWeight="600">{n.label}</text>}
                  </g>
                );
              })}
            </svg>
            {tip && (
              <div className="gr-tip" style={{ left: tip.x, top: tip.y }}>
                <div className="id">{tip.n.id} · {tip.n.kind === "lesson" ? "lesson" : "decision"}</div>
                {tip.n.title}
                <div className="pj">{tip.n.project}</div>
              </div>
            )}
            <div className="gr-stat">
              <span><b>{PM.nodes.length}</b> visible nodes</span>
              <span><b>{PM.edges.length}</b> edges</span>
              <span><b>{PM.clusters.length}</b> clusters</span>
              <span style={{ marginLeft: "auto", color: "var(--faint)" }}>sample of the {PM.stats.graphNodes}-node graph · click → record</span>
            </div>
          </div>

          <div className="gr-side">
            <div className="pm-card gr-panel">
              <div className="gr-ph"><Icon name="filter" size={13} /> Clusters</div>
              <div className="gr-leg">
                {PM.clusters.map((c) => {
                  const n = PM.nodes.filter((x) => x.cluster === c.id).length;
                  const off = activeCluster && activeCluster !== c.id;
                  return (
                    <div key={c.id} className={"gr-legrow" + (off ? " off" : "")}
                      onClick={() => setActiveCluster((a) => (a === c.id ? null : c.id))}>
                      <span className="sw" style={{ background: c.color }} />
                      {c.label}
                      <span className="n">{n}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="pm-card gr-panel">
              <div className="gr-ph"><Icon name="spark" size={13} style={{ color: "var(--accent-ink)" }} /> Unexpected connections</div>
              <div className="gr-unexp">
                {unexpected.map((e, i) => (
                  <div key={i} className="gr-urow" onClick={() => nav("detail", { id: e.from })}
                    onMouseEnter={() => setHover(e.from)} onMouseLeave={() => setHover(null)}>
                    <div className="top">{e.from} <Icon name="link" size={11} /> {e.to}<span className="conf">%{Math.round(e.conf * 100)}</span></div>
                    <div className="dd">{PM.byId[e.from] ? PM.byId[e.from].project : ""} ↔ {PM.byId[e.to] ? PM.byId[e.to].project : ""}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
  window.PMGraph = GraphView;
})();
