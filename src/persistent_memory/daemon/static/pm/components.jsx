// persistent-memory — shared UI components & icons. Exports to window.
(function () {
  const React = window.React;
  const h = React.createElement;

  // ---- Icon set (stroke, 18x18, currentColor) ----
  const P = {
    overview: "M3 12h3l2 5 4-12 2 7h4",
    decision: "M4 5h16v14H4zM9 12l2 2 4-4",
    lesson: "M9 18h6M10 21h4M12 3a6 6 0 0 1 4 10.5c-.7.7-1 1.3-1 2.5H9c0-1.2-.3-1.8-1-2.5A6 6 0 0 1 12 3z",
    project: "M3 7l9-4 9 4-9 4-9-4zM3 12l9 4 9-4M3 17l9 4 9-4",
    graph: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM7.5 7.5l3 6M16.5 7.5l-3 6",
    timeline: "M5 3v18M5 7h6M5 13h10M5 18h7M11 7a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM15 13a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM12 18a1.5 1.5 0 100-3 1.5 1.5 0 000 3z",
    health: "M3 12h3l2 4 3-9 2 6 1.5-3H21",
    search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
    queue: "M4 6h16M4 12h16M4 18h10M19 16l2 2-2 2",
    arrowLeft: "M15 19l-7-7 7-7",
    arrowRight: "M9 5l7 7-7 7",
    chevR: "M9 6l6 6-6 6",
    session: "M5 5h14v10H9l-4 4z",
    edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
    revert: "M9 7L4 12l5 5M4 12h11a5 5 0 0 1 0 10h-1",
    panel: "M4 5h16v14H4zM10 5v14",
    settings: "M12 9a3 3 0 100 6 3 3 0 000-6zM19 12a7 7 0 0 0-.1-1l2-1.6-2-3.4-2.4 1a7 7 0 0 0-1.7-1L14.5 2h-5l-.3 2.9a7 7 0 0 0-1.7 1l-2.4-1-2 3.4L5 11a7 7 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 1.7 1l.3 2.9h5l.3-2.9a7 7 0 0 0 1.7-1l2.4 1 2-3.4-2-1.6a7 7 0 0 0 .1-1z",
    link: "M9 15l6-6M10 6l1-1a4 4 0 0 1 6 6l-1 1M14 18l-1 1a4 4 0 0 1-6-6l1-1",
    dot: "M12 12m-3 0a3 3 0 1 0 6 0 3 3 0 1 0-6 0",
    spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18",
    close: "M6 6l12 12M18 6L6 18",
    filter: "M3 5h18l-7 8v5l-4 2v-7z",
  };
  function Icon({ name, size = 18, sw = 1.6, style }) {
    const d = P[name] || P.dot;
    return h("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: sw, strokeLinecap: "round", strokeLinejoin: "round", style }, h("path", { d }));
  }

  const STATUS_LABEL = { proposed: "proposed", accepted: "accepted", superseded: "superseded", reverted: "reverted" };
  const STATUS_FRIENDLY = { proposed: "pending", accepted: "approved", superseded: "replaced", reverted: "mistake" };

  function StatusPill({ status, friendly }) {
    return h("span", { className: "pm-pill " + status }, h("span", { className: "d" }), friendly ? STATUS_FRIENDLY[status] : STATUS_LABEL[status]);
  }

  function Importance({ value, w = 90, showVal = true }) {
    return h("span", { style: { display: "inline-flex", alignItems: "center", gap: 8 } },
      h("span", { className: "pm-meter", style: { width: w } }, h("i", { style: { clipPath: `inset(0 ${100 - value * 100}% 0 0)` } })),
      showVal && h("b", { className: "pm-mono", style: { fontSize: 12, color: "var(--txt-hi)", fontWeight: 600 } }, value.toFixed(2)));
  }

  function KindTag({ kind }) {
    return h("span", { className: "pm-kindtag " + kind }, kind === "decision" ? "DECISION" : "LESSON");
  }

  // relative-ish date pretty
  function fmtDate(d) { return d.slice(5).replace("-", "/"); }

  // make [[D-0001]] / [[L-0082]] cross-references in body text clickable
  const REF_RE = /\[\[([DLP]-\d{4})(?:\|[^\]]*)?\]\]/g;
  function renderRefs(text, nav) {
    if (!text || text.indexOf("[[") < 0) return text;
    const PM = window.PM;
    const out = [];
    let last = 0, m, k = 0;
    REF_RE.lastIndex = 0;
    while ((m = REF_RE.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      const id = m[1];
      const known = PM && PM.byId && PM.byId[id];
      out.push(known
        ? h("a", { key: "r" + (k++), className: "pm-ref", title: PM.byId[id].title, onClick: (e) => { e.stopPropagation(); nav && nav("detail", { id }); } }, id)
        : h("span", { key: "r" + (k++), className: "pm-ref missing", title: "record not found" }, id));
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  window.PMUI = { Icon, StatusPill, Importance, KindTag, fmtDate, renderRefs, STATUS_LABEL, STATUS_FRIENDLY };
})();
