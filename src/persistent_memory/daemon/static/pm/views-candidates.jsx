// persistent-memory — Supersession candidate review (graph cross-cluster links).
(function () {
  const React = window.React;
  const { useState, useEffect } = React;
  const { Icon } = window.PMUI;

  if (!document.getElementById("pm-cand-css")) {
    const s = document.createElement("style");
    s.id = "pm-cand-css";
    s.textContent = `
.cd-list{display:flex;flex-direction:column;gap:12px;margin-top:20px}
.cd-card{padding:16px 18px}
.cd-top{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.cd-rel{font-family:var(--font-mono);font-size:11px;color:var(--violet);background:color-mix(in srgb,var(--violet) 14%,transparent);padding:3px 9px;border-radius:999px}
.cd-score{font-family:var(--font-mono);font-size:12px;color:var(--txt-hi);font-weight:600;margin-left:auto}
.cd-pair{display:flex;align-items:center;gap:14px}
.cd-side{flex:1;min-width:0;padding:11px 13px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--panel-hi)}
.cd-side .role{font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;margin-bottom:5px}
.cd-side.old .role{color:var(--st-superseded)}
.cd-side.new .role{color:var(--st-accepted)}
.cd-side .lb{font-size:13px;color:var(--txt-hi);line-height:1.45}
.cd-side .rid{font-family:var(--font-mono);font-size:11px;color:var(--accent-ink);cursor:pointer;margin-top:4px;display:inline-block}
.cd-side .rid.none{color:var(--faint);cursor:default}
.cd-arrow{flex:0 0 auto;color:var(--faint);display:flex;flex-direction:column;align-items:center;gap:6px}
.cd-swap{font-size:11px;color:var(--accent-ink);cursor:pointer;border:1px solid var(--line);border-radius:999px;padding:3px 10px;background:none;font-family:inherit}
.cd-swap:hover{border-color:var(--accent-line)}
.cd-files{font-family:var(--font-mono);font-size:10.5px;color:var(--faint);margin-top:10px}
.cd-acts{display:flex;gap:9px;margin-top:13px}
.cd-done{margin-top:13px;font-size:12.5px;color:var(--dim)}
`;
    document.head.appendChild(s);
  }

  function RecordRef({ id, nav }) {
    if (!id) return <span className="rid none">record ID could not be resolved</span>;
    const known = window.PM.byId && window.PM.byId[id];
    return <a className="rid" title={known ? known.title : id} onClick={() => known && nav("detail", { id })}>{id}</a>;
  }

  function CandidateCard({ cand, nav, flash }) {
    const [swapped, setSwapped] = useState(false);
    const [done, setDone] = useState(null);
    const oldLabel = swapped ? cand.target_label : cand.source_label;
    const newLabel = swapped ? cand.source_label : cand.target_label;
    const oldId = swapped ? cand.target_id : cand.source_id;
    const newId = swapped ? cand.source_id : cand.target_id;
    const canLink = !!(oldId && newId);

    const onLink = () => {
      window.PM_API.linkSupersession(oldId, newId).then((res) => {
        if (res.ok) { setDone("✓ Linked — " + oldId + " is now superseded by " + newId + "."); flash("✓ Linked · " + oldId + " → " + newId); }
        else flash("✕ Link failed (HTTP " + res.status + ")");
      });
    };
    const onDismiss = () => {
      window.PM_API.dismissCandidate({
        source_id: cand.source_id, source_label: cand.source_label,
        target_id: cand.target_id, target_label: cand.target_label,
      }).then((ok) => {
        if (ok) { setDone("Dismissed — this pair will not be suggested again."); flash("Dismissed"); }
        else flash("✕ Dismiss failed");
      });
    };

    return (
      <div className="pm-card cd-card">
        <div className="cd-top">
          <Icon name="link" size={15} style={{ color: "var(--violet)" }} />
          <span className="cd-rel">{cand.relation || "related"}</span>
          <span className="cd-score">score {cand.score.toFixed(2)}</span>
        </div>
        <div className="cd-pair">
          <div className="cd-side old">
            <div className="role">Old — will be superseded</div>
            <div className="lb">{oldLabel}</div>
            <RecordRef id={oldId} nav={nav} />
          </div>
          <div className="cd-arrow">
            <Icon name="arrowRight" size={17} />
            <button className="cd-swap" onClick={() => setSwapped((v) => !v)}>swap direction</button>
          </div>
          <div className="cd-side new">
            <div className="role">New — current record</div>
            <div className="lb">{newLabel}</div>
            <RecordRef id={newId} nav={nav} />
          </div>
        </div>
        {cand.source_files && cand.source_files.length > 0 && <div className="cd-files">source: {cand.source_files.join(", ")}</div>}
        {done ? <div className="cd-done">{done}</div> : (
          <div className="cd-acts">
            <button className="pm-btn accent" disabled={!canLink}
              title={canLink ? "Link the old record to the new/current record" : "Record IDs could not be resolved — cannot link"}
              onClick={onLink}><Icon name="link" size={14} /> Link — target: new/current record</button>
            <button className="pm-btn" onClick={onDismiss}><Icon name="close" size={13} /> Dismiss</button>
          </div>
        )}
      </div>
    );
  }

  function CandidatesView({ nav }) {
    const [cands, setCands] = useState(null);
    const [toast, setToast] = useState(null);
    const flash = (msg) => { setToast(msg); clearTimeout(window.__pmCandToast); window.__pmCandToast = setTimeout(() => setToast(null), 1900); };

    useEffect(() => {
      let active = true;
      window.PM_API.fetchSupersessionCandidates().then((data) => { if (active) setCands(data.candidates || []); });
      return () => { active = false; };
    }, []);

    return (
      <div className="pm-page fade-in">
        <div className="pm-eyebrow">Graph cross-cluster links · consolidation suggestions</div>
        <h1 className="pm-h" style={{ marginTop: 6 }}>Supersession candidates</h1>
        {cands === null && <div className="pm-empty" style={{ paddingTop: 30 }}>Loading…</div>}
        {cands !== null && cands.length === 0 && (
          <div className="pm-empty" style={{ paddingTop: 30 }}>No candidates. If the graph is stale, run consolidation first.</div>
        )}
        {cands !== null && cands.length > 0 && (
          <div className="cd-list">
            {cands.map((c, i) => <CandidateCard key={i} cand={c} nav={nav} flash={flash} />)}
          </div>
        )}
        {toast && <div className="pm-toast">{toast}</div>}
      </div>
    );
  }

  window.PMCandidates = CandidatesView;
})();
