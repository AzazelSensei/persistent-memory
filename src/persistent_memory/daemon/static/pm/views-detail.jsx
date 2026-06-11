// persistent-memory — Detail view (hero). Live record: content + RAG source
// + relationship mini-graph + actions. Uses Signal tokens.
(function () {
  const React = window.React;
  const { useState, useEffect } = React;
  const { Icon, StatusPill, Importance, KindTag, renderRefs } = window.PMUI;

  if (!document.getElementById("pm-detail-css")) {
    const s = document.createElement("style");
    s.id = "pm-detail-css";
    s.textContent = `
.d-wrap{display:flex;gap:0;align-items:flex-start}
.d-main{flex:1;min-width:0;padding-right:28px}
.d-back{display:inline-flex;align-items:center;gap:7px;color:var(--dim);font-size:13px;cursor:pointer;
  background:none;border:0;font-family:inherit;padding:0;margin-bottom:18px}
.d-back:hover{color:var(--txt)}
.d-head{display:flex;align-items:flex-start;gap:18px}
.d-head .l{flex:1;min-width:0}
.d-meta{display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.d-id{font-family:var(--font-mono);font-size:12px;color:var(--faint);letter-spacing:.5px}
.d-h1{font-size:25px;line-height:1.28;color:var(--txt-hi);font-weight:600;letter-spacing:-0.4px;margin:12px 0 0;max-width:30ch}
.d-tags{display:flex;gap:7px;margin-top:14px;flex-wrap:wrap}
.d-impcard{flex:0 0 218px;padding:14px 16px}
.d-impcard .lab{display:flex;justify-content:space-between;font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--faint);margin-bottom:8px}
.d-impcard .val{font-family:var(--font-mono);font-size:22px;font-weight:600;color:var(--st-proposed)}
.d-impcard .meta2{display:flex;gap:16px;margin-top:11px;font-size:11.5px;color:var(--dim)}
.d-impcard .meta2 b{color:var(--txt-hi);font-family:var(--font-mono)}
.d-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap);margin-top:22px}
.d-sec{padding:var(--pad);}
.d-sec.full{grid-column:1/-1}
.d-sec-h{display:flex;align-items:center;gap:9px;margin-bottom:10px}
.d-sec-h .bar{width:3px;height:14px;border-radius:2px;background:var(--accent)}
.d-sec-h .l{font-size:12.5px;font-weight:600;color:var(--txt-hi)}
.d-sec-h .e{margin-left:auto;font-family:var(--font-mono);font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--faint)}
.d-sec p{margin:0;font-size:14px;line-height:1.7;color:var(--txt)}
/* right rail */
.d-rail{width:372px;flex:0 0 372px;align-self:stretch;border-left:1px solid var(--line);
  margin-left:0;padding-left:24px;display:flex;flex-direction:column;gap:18px}
.d-panel-h{display:flex;align-items:center;gap:8px;font-size:10.5px;text-transform:uppercase;letter-spacing:1px;color:var(--faint);margin-bottom:13px}
.d-panel-h .n{margin-left:auto;font-family:var(--font-mono);letter-spacing:0;text-transform:none;color:var(--accent-ink)}
.d-sess{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--panel-hi);cursor:pointer;margin-bottom:15px}
.d-sess:hover{border-color:var(--accent-line)}
.d-sess .dt{width:8px;height:8px;border-radius:50%;background:var(--st-accepted);box-shadow:var(--glow) var(--st-accepted);flex:0 0 auto}
.d-sess .ti{font-family:var(--font-mono);font-size:12px;color:var(--txt)}
.d-sess .su{font-size:11px;color:var(--dim);margin-top:1px}
.d-pass{margin-bottom:14px}
.d-pass .row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.d-pass .sc{font-family:var(--font-mono);font-size:11px;color:var(--accent-ink);flex:0 0 auto;font-weight:600}
.d-pass .scbar{flex:1;height:4px;border-radius:999px;background:var(--line2);overflow:hidden}
.d-pass .scbar i{display:block;height:100%;background:var(--accent)}
.d-pass .tm{font-family:var(--font-mono);font-size:10.5px;color:var(--faint);flex:0 0 auto}
.d-pass p{margin:0;font-size:12.5px;line-height:1.55;color:var(--dim)}
.d-rel{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line);cursor:pointer}
.d-rel:hover .rt{color:var(--txt-hi)}
.d-rel .k{font-size:9px;font-weight:700;letter-spacing:.6px;color:var(--faint);border:1px solid var(--line2);border-radius:5px;padding:3px 6px;flex:0 0 auto}
.d-rel .rid{font-family:var(--font-mono);font-size:10.5px;color:var(--accent-ink);margin-bottom:2px}
.d-rel .rt{font-size:12.5px;color:var(--dim);line-height:1.4}
.d-rel .rt.strike{text-decoration:line-through;opacity:.6}
.d-graphbox{padding:6px 0}
.d-act{display:flex;flex-direction:column;gap:9px;margin-top:4px;padding-top:16px;border-top:1px solid var(--line)}
.d-act .row{display:flex;gap:9px}
.d-act .row .pm-btn{flex:1}
.d-banner{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:var(--r-sm);font-size:12.5px;margin-top:14px}
.d-banner.done{background:color-mix(in srgb,var(--st-accepted) 13%,var(--panel));color:var(--st-accepted);border:1px solid color-mix(in srgb,var(--st-accepted) 35%,var(--line2))}
.d-banner.no{background:color-mix(in srgb,var(--st-reverted) 12%,var(--panel));color:var(--st-reverted);border:1px solid color-mix(in srgb,var(--st-reverted) 32%,var(--line2))}
`;
    document.head.appendChild(s);
  }

  function MiniGraph({ rec, nav }) {
    const PM = window.PM;
    const rels = [];
    if (rec.relationships.supersedes) rels.push({ id: rec.relationships.supersedes, kind: "supersedes" });
    (rec.relationships.related || []).forEach((id) => rels.push({ id, kind: "related" }));
    if (rec.relationships.supersededBy) rels.push({ id: rec.relationships.supersededBy, kind: "superseded-by" });
    const cx = 165, cy = 26 + rels.length * 31 / 2;
    const W = 330, H = Math.max(110, rels.length * 56 + 20);
    const cyMid = H / 2;
    const accent = "var(--accent)";
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
        <defs>
          <marker id="pmArr" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="var(--line2)" />
          </marker>
        </defs>
        {rels.map((r, i) => {
          const ny = (H / (rels.length + 1)) * (i + 1);
          return <line key={"e" + i} x1="78" y1={cyMid} x2="232" y2={ny} stroke="var(--line2)" strokeWidth="1.4" markerEnd="url(#pmArr)" />;
        })}
        {/* center node */}
        <circle cx="60" cy={cyMid} r="20" fill="var(--accent-soft)" stroke={accent} strokeWidth="2" />
        <text x="60" y={cyMid + 3.5} textAnchor="middle" fontSize="9.5" fill="var(--accent-ink)" fontFamily="var(--font-mono)" fontWeight="600">{rec.id.replace(/^([A-Z]+)-0*/, "$1")}</text>
        {rels.map((r, i) => {
          const ny = (H / (rels.length + 1)) * (i + 1);
          const isLes = PM.byId[r.id] ? PM.byId[r.id].kind === "lesson" : r.id.startsWith("L");
          const col = r.kind === "supersedes" || r.kind === "superseded-by" ? "var(--st-superseded)" : (isLes ? "var(--violet)" : "var(--accent)");
          return (
            <g key={"n" + i} style={{ cursor: "pointer" }} onClick={() => nav("detail", { id: r.id })}>
              <circle cx="250" cy={ny} r="14" fill="var(--panel)" stroke={col} strokeWidth="1.5"
                strokeDasharray={r.kind.indexOf("supersed") === 0 ? "3 2" : "0"} />
              <text x="250" y={ny + 3} textAnchor="middle" fontSize="8.5" fill={col} fontFamily="var(--font-mono)">{r.id.replace(/^([A-Z]+)-0*/, "$1")}</text>
              <text x="270" y={ny + 3} fontSize="8.5" fill="var(--faint)" fontFamily="var(--font-mono)">{r.kind}</text>
            </g>
          );
        })}
      </svg>
    );
  }

  function DetailView({ rec, nav, onAction, liveStatus }) {
    const PM = window.PM;
    const [passages, setPassages] = useState(rec.source.passages || []);
    useEffect(() => {
      let alive = true;
      setPassages(rec.source.passages || []);
      if (window.PM_API && window.PM_API.fetchSource) {
        window.PM_API.fetchSource(rec.id).then((d) => { if (alive && d && d.passages) setPassages(d.passages); });
      }
      return () => { alive = false; };
    }, [rec.id]);
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState("");
    const [editErr, setEditErr] = useState("");
    useEffect(() => { setEditing(false); setEditErr(""); }, [rec.id]);
    const openEdit = () => {
      setEditErr("");
      window.PM_API && window.PM_API.fetchRaw(rec.id).then((d) => {
        if (d && typeof d.body === "string") { setDraft(d.body); setEditing(true); }
        else setEditErr("Could not fetch raw content");
      });
    };
    const saveEdit = () => {
      setEditErr("");
      window.PM_API.saveBody(rec.id, draft).then((res) => {
        if (res.ok) window.location.reload();
        else setEditErr(res.status === 409 ? "Accepted record — body cannot be modified" : "Save failed (HTTP " + res.status + ")");
      });
    };
    const status = liveStatus || rec.status;
    const half = rec.sections.slice(0, 2);
    const full = rec.sections.slice(2);
    const sup = rec.relationships.supersedes ? PM.byId[rec.relationships.supersedes] : null;
    const related = (rec.relationships.related || []).map((id) => PM.byId[id]).filter(Boolean);
    const pending = status === "proposed";
    const impColor = rec.importance > 0.66 ? "var(--st-reverted)" : rec.importance > 0.4 ? "var(--st-proposed)" : "var(--st-accepted)";

    return (
      <div className="pm-page fade-in" key={rec.id}>
        <button className="d-back" onClick={() => nav(rec.kind === "lesson" ? "lessons" : "decisions")}>
          <Icon name="arrowLeft" size={15} /> {rec.kind === "lesson" ? "Lessons" : "Decisions"}
        </button>
        <div className="d-wrap">
          <div className="d-main">
            <div className="d-head">
              <div className="l">
                <div className="d-meta">
                  <StatusPill status={status} />
                  <KindTag kind={rec.kind} />
                  <span className="d-id">{rec.id} · {rec.project}</span>
                </div>
                <h1 className="d-h1">{rec.title}</h1>
                <div className="d-tags">{rec.tags.map((t) => <span className="pm-tag" key={t}>{t}</span>)}</div>
              </div>
              <div className="pm-card d-impcard">
                <div className="lab"><span>Importance score</span><span>0–1</span></div>
                <div className="val" style={{ color: impColor }}>{rec.importance.toFixed(2)}</div>
                <div className="pm-meter" style={{ marginTop: 9 }}><i style={{ clipPath: `inset(0 ${100 - rec.importance * 100}% 0 0)` }} /></div>
                <div className="meta2"><span>date <b>{rec.date}</b></span></div>
              </div>
            </div>
            {editing ? (
              <div className="d-grid" style={{ gridTemplateColumns: "1fr" }}>
                <div className="pm-card d-sec full">
                  <div className="d-sec-h"><span className="bar" /><span className="l">Raw content · markdown</span><span className="e">edit</span></div>
                  <textarea value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false}
                    style={{ width: "100%", minHeight: 400, background: "var(--bg2)", color: "var(--txt-hi)", border: "1px solid var(--line2)", borderRadius: "var(--r-sm)", padding: 12, fontFamily: "var(--font-mono)", fontSize: 12.5, lineHeight: 1.6, resize: "vertical", outline: "none" }} />
                  <div style={{ display: "flex", gap: 9, marginTop: 12, alignItems: "center" }}>
                    <button className="pm-btn accent" onClick={saveEdit}><Icon name="decision" size={15} /> Save</button>
                    <button className="pm-btn ghost" onClick={() => setEditing(false)}>Cancel</button>
                    {editErr && <span style={{ color: "var(--st-reverted)", fontSize: 12.5 }}>{editErr}</span>}
                    <span style={{ marginLeft: "auto", fontSize: 11.5, color: "var(--faint)" }}>title = first # line · frontmatter & source section preserved</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="d-grid">
                {half.map((sec) => (
                  <div className="pm-card d-sec" key={sec.key || sec.en}>
                    <div className="d-sec-h"><span className="bar" /><span className="l">{sec.label}</span><span className="e">{sec.en}</span></div>
                    <p>{renderRefs(sec.text, nav)}</p>
                  </div>
                ))}
                {full.map((sec) => (
                  <div className="pm-card d-sec full" key={sec.key || sec.en}>
                    <div className="d-sec-h"><span className="bar" /><span className="l">{sec.label}</span><span className="e">{sec.en}</span></div>
                    <p>{renderRefs(sec.text, nav)}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="d-rail">
            <div>
              <div className="d-panel-h"><Icon name="session" size={13} /> Source · RAG <span className="n">{passages.length} passages</span></div>
              <div className="d-sess">
                <span className="dt" />
                <span style={{ flex: 1 }}>
                  <div className="ti">{rec.source.session}</div>
                  <div className="su">{rec.source.sessionTitle} · go to session →</div>
                </span>
              </div>
              {passages.length === 0 && <div style={{ fontSize: 12, color: "var(--faint)", fontStyle: "italic", marginBottom: 6 }}>No linked passages for this record.</div>}
              {passages.map((p, i) => (
                <div className="d-pass" key={i}>
                  <div className="row">
                    <span className="sc">{p.score.toFixed(2)}</span>
                    <span className="scbar"><i style={{ width: p.score * 100 + "%" }} /></span>
                    <span className="tm">{p.time}</span>
                  </div>
                  <p>{p.text}</p>
                </div>
              ))}
            </div>

            <div>
              <div className="d-panel-h"><Icon name="graph" size={13} /> Relationships</div>
              {sup && (
                <div className="d-rel" onClick={() => nav("detail", { id: sup.id })}>
                  <span className="k">SUPERSEDES</span>
                  <span><div className="rid">{sup.id}</div><span className="rt strike">{sup.title}</span></span>
                </div>
              )}
              {rec.relationships.supersededBy && PM.byId[rec.relationships.supersededBy] && (
                <div className="d-rel" onClick={() => nav("detail", { id: rec.relationships.supersededBy })}>
                  <span className="k">SUPERSEDED-BY</span>
                  <span><div className="rid">{rec.relationships.supersededBy}</div><span className="rt">{PM.byId[rec.relationships.supersededBy].title}</span></span>
                </div>
              )}
              {related.map((r) => (
                <div className="d-rel" key={r.id} onClick={() => nav("detail", { id: r.id })}>
                  <span className="k">{r.kind === "lesson" ? "LESSON" : "RELATED"}</span>
                  <span><div className="rid">{r.id} · {r.project}</div><span className="rt">{r.title}</span></span>
                </div>
              ))}
              <div className="d-graphbox"><MiniGraph rec={rec} nav={nav} /></div>
            </div>

            <div className="d-act">
              {pending ? (
                <>
                  <div className="row">
                    <button className="pm-btn ok" onClick={() => onAction(rec.id, "accepted")}><Icon name="decision" size={15} /> {t("ui.btn.approve", "Approve")} <span className="pm-kbd" style={{ marginLeft: 2 }}>A</span></button>
                    <button className="pm-btn no" onClick={() => onAction(rec.id, "reverted")}><Icon name="close" size={15} /> {t("ui.btn.reject", "Reject")} <span className="pm-kbd" style={{ marginLeft: 2 }}>R</span></button>
                  </div>
                  <button className="pm-btn ghost" style={{ justifyContent: "flex-start" }} onClick={openEdit}><Icon name="edit" size={15} /> {t("ui.detail.edit", "Edit")}</button>
                </>
              ) : (
                <div className={"d-banner " + (status === "reverted" ? "no" : "done")}>
                  <Icon name={status === "reverted" ? "revert" : "decision"} size={15} />
                  {status === "accepted" && "Approved — accepted decision."}
                  {status === "reverted" && "Marked as a mistake / rejected."}
                  {status === "superseded" && "This record was superseded by a newer decision."}
                </div>
              )}
              <button className="pm-btn ghost" style={{ justifyContent: "flex-start" }}><Icon name="revert" size={15} /> Revert as mistake</button>
            </div>
          </div>
        </div>
      </div>
    );
  }
  window.PMDetail = DetailView;
})();
