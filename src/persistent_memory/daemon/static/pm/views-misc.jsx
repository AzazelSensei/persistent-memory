// persistent-memory — lighter surfaces: Timeline, Search, Health/audit.
(function () {
  const React = window.React;
  const { useState, useMemo } = React;
  const { Icon, StatusPill, KindTag, Importance, fmtDate } = window.PMUI;

  if (!document.getElementById("pm-misc-css")) {
    const s = document.createElement("style");
    s.id = "pm-misc-css";
    s.textContent = `
.tl-wrap{margin-top:20px;position:relative;padding-left:22px}
.tl-wrap::before{content:"";position:absolute;left:5px;top:6px;bottom:6px;width:2px;background:var(--line)}
.tl-day{margin-bottom:8px;margin-top:22px;font-family:var(--font-mono);font-size:12px;color:var(--faint);position:relative}
.tl-day:first-child{margin-top:0}
.tl-row{display:flex;align-items:center;gap:13px;padding:9px 14px;border-radius:var(--r-sm);cursor:pointer;position:relative;margin-bottom:4px}
.tl-row:hover{background:var(--panel-hi)}
.tl-row::before{content:"";position:absolute;left:-21px;width:11px;height:11px;border-radius:50%;border:2px solid var(--bg);box-sizing:content-box}
.tl-row .tm{font-family:var(--font-mono);font-size:11px;color:var(--faint);flex:0 0 42px}
.tl-row .rid{font-family:var(--font-mono);font-size:11px;color:var(--accent-ink);flex:0 0 auto;white-space:nowrap}
.tl-row .tt{flex:1;min-width:0;font-size:13px;color:var(--txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tl-row .pj{font-family:var(--font-mono);font-size:11px;color:var(--dim);white-space:nowrap}

.se-box{display:flex;align-items:center;gap:11px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 18px;margin-top:18px}
.se-box:focus-within{border-color:var(--accent-line)}
.se-box input{flex:1;border:0;background:none;color:var(--txt-hi);font-family:inherit;font-size:17px;outline:none}
.se-box input::placeholder{color:var(--faint)}
.se-meta{display:flex;gap:14px;margin:14px 2px 6px;font-size:12px;color:var(--faint);font-family:var(--font-mono)}
.se-meta span{white-space:nowrap}
.se-card .top span{white-space:nowrap}
.se-res{display:flex;flex-direction:column;gap:8px;margin-top:8px}
.se-card{padding:13px 16px;cursor:pointer}
.se-card:hover{border-color:var(--line2)}
.se-card .top{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.se-card .ti{font-size:14px;color:var(--txt-hi);font-weight:500}
.se-card .sn{font-size:12px;color:var(--dim);line-height:1.5}
.se-card mark{background:color-mix(in srgb,var(--accent) 28%,transparent);color:var(--txt-hi);border-radius:3px;padding:0 2px}

.he-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--gap);margin-top:20px}
.he-kpi{padding:14px 16px;text-align:left}
.he-kpi .v{font-family:var(--font-mono);font-size:26px;font-weight:600;margin-top:6px}
.he-kpi .l{font-size:11px;color:var(--faint);text-transform:uppercase;letter-spacing:.6px;display:flex;align-items:center;gap:7px}
.he-list{display:flex;flex-direction:column;gap:10px;margin-top:var(--gap)}
.he-row{display:flex;align-items:flex-start;gap:14px;padding:15px 18px;cursor:pointer}
.he-row:hover{border-color:var(--line2)}
.he-row .ic{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
.he-row .ht{font-size:14px;color:var(--txt-hi);font-weight:600}
.he-row .hd{font-size:12.5px;color:var(--dim);margin-top:3px;line-height:1.5}
.he-row .badge{font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;padding:3px 8px;border-radius:999px;flex:0 0 auto}
`;
    document.head.appendChild(s);
  }

  const ST_COL = { proposed: "var(--st-proposed)", accepted: "var(--st-accepted)", superseded: "var(--st-superseded)", reverted: "var(--st-reverted)" };

  function TimelineView({ nav, statuses }) {
    const PM = window.PM;
    const grouped = useMemo(() => {
      const recs = [...PM.all].sort((a, b) => b.date.localeCompare(a.date));
      const g = {};
      recs.forEach((r) => { (g[r.date] = g[r.date] || []).push(r); });
      return Object.entries(g);
    }, []);
    return (
      <div className="pm-page fade-in">
        <div className="pm-eyebrow">Chronological flow of memory</div>
        <h1 className="pm-h" style={{ marginTop: 6 }}>Timeline</h1>
        <div className="tl-wrap">
          {grouped.map(([day, recs]) => (
            <div key={day}>
              <div className="tl-day">{day}</div>
              {recs.map((r) => {
                const st = statuses[r.id] || r.status;
                return (
                  <div key={r.id} className="tl-row" onClick={() => nav("detail", { id: r.id })}>
                    <span style={{ position: "absolute", left: -21, width: 11, height: 11, borderRadius: "50%", background: ST_COL[st], border: "2px solid var(--bg)" }} />
                    <span className="rid">{r.id}</span>
                    <KindTag kind={r.kind} />
                    <span className="tt">{r.title}</span>
                    <span className="pj">{r.project}</span>
                    <span className="stat" style={{ flex: "0 0 auto" }}><StatusPill status={st} /></span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    );
  }

  function hl(text, q) {
    if (!q) return text;
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return text;
    return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
  }

  function SearchView({ nav, statuses, initialQ }) {
    const PM = window.PM;
    const [q, setQ] = useState(initialQ || "");
    const results = useMemo(() => {
      if (!q.trim()) return [];
      const lq = q.toLowerCase();
      return PM.all.map((r) => {
        let snippet = "", inSnip = false;
        for (const sec of r.sections) {
          if (sec.text.toLowerCase().includes(lq)) { snippet = sec.text; inSnip = true; break; }
        }
        const hit = r.title.toLowerCase().includes(lq) || r.id.toLowerCase().includes(lq) || r.tags.join(" ").toLowerCase().includes(lq) || inSnip;
        return hit ? { r, snippet: snippet || r.sections[0].text } : null;
      }).filter(Boolean).slice(0, 40);
    }, [q]);

    return (
      <div className="pm-page fade-in">
        <div className="pm-eyebrow">Bilingual search · TR / EN</div>
        <h1 className="pm-h" style={{ marginTop: 6 }}>Search</h1>
        <div className="se-box">
          <Icon name="search" size={20} style={{ color: "var(--accent-ink)" }} />
          <input autoFocus placeholder={t("ui.search.hint", "decision, lesson, tag, content… (e.g. embedding, deadlock, canary)")} value={q} onChange={(e) => setQ(e.target.value)} />
          {q && <span className="pm-kbd" style={{ cursor: "pointer" }} onClick={() => setQ("")}>clear</span>}
        </div>
        {q.trim() ? (
          <>
            <div className="se-meta"><span>{results.length} results</span><span>title · tag · content</span></div>
            <div className="se-res">
              {results.map(({ r, snippet }) => {
                const st = statuses[r.id] || r.status;
                return (
                  <div key={r.id} className="pm-card se-card" onClick={() => nav("detail", { id: r.id })}>
                    <div className="top">
                      <StatusPill status={st} />
                      <KindTag kind={r.kind} />
                      <span className="pm-mono" style={{ fontSize: 11, color: "var(--faint)" }}>{r.id} · {r.project}</span>
                    </div>
                    <div className="ti">{hl(r.title, q)}</div>
                    <div className="sn">{hl(snippet.length > 150 ? snippet.slice(0, 150) + "…" : snippet, q)}</div>
                  </div>
                );
              })}
              {results.length === 0 && <div className="pm-empty">No results for "{q}".</div>}
            </div>
          </>
        ) : (
          <div className="pm-empty" style={{ paddingTop: 40 }}>Start typing to search. Content is indexed in both Turkish and English.</div>
        )}
      </div>
    );
  }

  function HealthView({ nav, statuses }) {
    const PM = window.PM;
    const cfg = {
      conflict: ["link", "var(--st-reverted)", "Conflict"],
      stale: ["timeline", "var(--st-proposed)", "Stale"],
      missing: ["session", "var(--st-superseded)", "Missing"],
      duplicate: ["graph", "var(--violet)", "Duplicate"],
    };
    const kpis = [
      [t("ui.health.inconsistencies", "Inconsistencies"), PM.health.filter((h) => h.level === "conflict").length, "var(--st-reverted)", "link"],
      [t("ui.health.stale_proposed", "Stale 'proposed'"), 5, "var(--st-proposed)", "timeline"],
      [t("ui.health.missing_source", "Missing source"), 3, "var(--st-superseded)", "session"],
      [t("ui.health.possible_duplicates", "Possible duplicates"), PM.health.filter((h) => h.level === "duplicate").length, "var(--violet)", "graph"],
    ];
    return (
      <div className="pm-page fade-in">
        <div className="pm-eyebrow">Consistency · missing · conflicts · staleness</div>
        <h1 className="pm-h" style={{ marginTop: 6 }}>Health & audit</h1>
        <div className="he-grid">
          {kpis.map(([l, v, c, ic]) => (
            <div key={l} className="pm-card he-kpi">
              <div className="l"><Icon name={ic} size={13} style={{ color: c }} /> {l}</div>
              <div className="v" style={{ color: v > 0 ? c : "var(--txt-hi)" }}>{v}</div>
            </div>
          ))}
        </div>
        <div className="he-list">
          {PM.health.map((hh, i) => {
            const [ic, col, lbl] = cfg[hh.level];
            return (
              <div key={i} className="pm-card he-row" onClick={() => hh.ids[0] && nav("detail", { id: hh.ids[0] })}>
                <span className="ic" style={{ background: `color-mix(in srgb, ${col} 16%, transparent)`, color: col }}><Icon name={ic} size={17} /></span>
                <div style={{ flex: 1 }}>
                  <div className="ht">{hh.title}</div>
                  <div className="hd">{hh.detail}</div>
                </div>
                <span className="badge" style={{ background: `color-mix(in srgb, ${col} 15%, transparent)`, color: col }}>{lbl}</span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  window.PMTimeline = TimelineView;
  window.PMSearch = SearchView;
  window.PMHealth = HealthView;
})();
