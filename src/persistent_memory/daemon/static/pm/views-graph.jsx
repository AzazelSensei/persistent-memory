// persistent-memory — Graph view. Cross-project knowledge graph:
// force-directed layout, zoom/pan, type/status/importance visual encoding,
// hover-to-highlight neighbourhood, click node -> record.
(function () {
  const React = window.React;
  const { useState, useMemo, useRef, useEffect } = React;
  const { Icon, pmById, StatusPill, Importance, KindTag } = window.PMUI;

  if (!document.getElementById("pm-graph-css")) {
    const s = document.createElement("style");
    s.id = "pm-graph-css";
    s.textContent = `
.gr-wrap{display:flex;gap:var(--gap);margin-top:16px;align-items:flex-start}
.gr-canvas{flex:1;min-width:0;border:1px solid var(--line);border-radius:var(--r);background:
  radial-gradient(circle at 30% 20%, color-mix(in srgb,var(--accent) 6%,var(--panel)), var(--panel) 60%);
  overflow:hidden;position:relative;cursor:grab}
.gr-canvas.dragging{cursor:grabbing}
.gr-canvas svg{display:block;width:100%;height:560px}
.gr-side{width:288px;flex:0 0 288px;display:flex;flex-direction:column;gap:var(--gap);max-height:620px;overflow-y:auto}
.gr-panel{padding:14px 16px}
.gr-ph{font-size:10.5px;text-transform:uppercase;letter-spacing:1px;color:var(--faint);margin-bottom:11px;display:flex;align-items:center;gap:7px;white-space:nowrap}
.gr-leg{display:flex;flex-direction:column;gap:3px}
.gr-legrow{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:var(--r-sm);cursor:pointer;font-size:12.5px;color:var(--txt);white-space:nowrap;border:0;background:none;width:100%;text-align:left;font-family:inherit}
.gr-legrow:hover{background:var(--panel-hi)}
.gr-legrow.off{opacity:.4}
.gr-legrow .sw{width:11px;height:11px;border-radius:4px;flex:0 0 auto}
.gr-legrow .n{margin-left:auto;flex:0 0 auto;font-family:var(--font-mono);font-size:11px;color:var(--faint)}
.gr-leglabel{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-legsmalltag{font-size:9.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--faint);white-space:nowrap}
.gr-keyrow{display:flex;align-items:center;gap:9px;padding:5px 8px;font-size:12px;color:var(--txt)}
.gr-keyrow svg{flex:0 0 auto}
.gr-keydesc{margin-left:auto;color:var(--faint);font-size:10.5px}
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
.gr-mesh{pointer-events:none}
.gr-settle{position:absolute;bottom:10px;left:14px;font-size:10.5px;font-family:var(--font-mono);color:var(--faint);pointer-events:none}
.gr-search{width:210px;flex:0 0 auto}
.gr-stat{display:flex;gap:16px;padding:10px 16px;border-top:1px solid var(--line);font-size:11.5px;color:var(--dim)}
.gr-stat span{white-space:nowrap}
.gr-stat b{font-family:var(--font-mono);color:var(--txt-hi)}
@keyframes gr-flow{to{stroke-dashoffset:-24}}
.gr-edge-unexp{animation:gr-flow 1.1s linear infinite}
.gr-node{transition:opacity 150ms ease}
.gr-canvas svg line{transition:opacity 150ms ease, stroke-width 150ms ease}
@media (prefers-reduced-motion: reduce){
  .gr-edge-unexp{animation:none}
  .gr-node{transition:none}
  .gr-canvas svg line{transition:none}
  .fade-in{animation:none}
}
.gr-toolbar{display:flex;align-items:center;gap:10px;margin:14px 0 4px;flex-wrap:wrap}
.gr-chips{display:flex;gap:6px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);padding:3px}
.gr-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:calc(var(--r-sm) - 1px);font-size:12px;color:var(--dim);cursor:pointer;border:0;background:none;font-family:inherit}
.gr-chip:hover{color:var(--txt)}
.gr-chip.on{background:var(--accent-soft);color:var(--accent-ink)}
.gr-select{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);color:var(--txt);font-family:inherit;font-size:12.5px;padding:7px 9px;cursor:pointer}
.gr-matchcount{font-family:var(--font-mono);font-size:11px;color:var(--faint);white-space:nowrap}
.gr-filtercount{display:flex;align-items:center;gap:8px;font-family:var(--font-mono);font-size:11px;color:var(--accent-ink);white-space:nowrap}
.gr-vh{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.gr-ph .n{margin-left:auto;font-family:var(--font-mono);font-size:11px;color:var(--faint)}
.gr-panelclose{margin-left:auto;background:none;border:0;color:var(--faint);cursor:pointer;display:inline-flex;padding:2px}
.gr-panelclose:hover{color:var(--txt)}
.gr-detail{display:flex;flex-direction:column;gap:9px}
.gr-d-id{font-family:var(--font-mono);font-size:11px;color:var(--accent-ink)}
.gr-d-title{font-size:13.5px;color:var(--txt-hi);font-weight:600;line-height:1.4}
.gr-d-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.gr-d-row{display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--dim)}
.gr-d-row b{color:var(--txt-hi);font-family:var(--font-mono);font-weight:600}
.gr-neigh{display:flex;flex-direction:column;gap:4px;max-height:220px;overflow-y:auto}
.gr-neighrow{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:var(--r-sm);cursor:pointer;font-size:11.5px;border:0;background:none;width:100%;text-align:left;font-family:inherit;color:var(--txt)}
.gr-neighrow:hover{background:var(--panel-hi)}
.gr-neighrow .id{font-family:var(--font-mono);color:var(--accent-ink)}
.gr-neighrow .ty{color:var(--faint);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-neighrow .cf{font-family:var(--font-mono);color:var(--dim)}
.gr-legend-sub{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--faint);margin:12px 0 6px}
.gr-legend-sub:first-of-type{margin-top:2px}
.gr-tablewrap{margin-top:16px;overflow-x:auto;border:1px solid var(--line);border-radius:var(--r)}
.gr-table{width:100%;border-collapse:collapse;font-size:12.5px}
.gr-table caption{text-align:left;padding:12px 14px;color:var(--txt-hi);font-weight:600;font-size:13px;border-bottom:1px solid var(--line)}
.gr-table th,.gr-table td{padding:9px 14px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
.gr-table th{color:var(--faint);font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;background:var(--bg2);position:sticky;top:0}
.gr-table td{color:var(--txt)}
.gr-table tbody tr:hover{background:var(--panel-hi)}
.gr-table .id{font-family:var(--font-mono);color:var(--accent-ink)}
.gr-table .ti{max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-idbtn{border:0;background:none;padding:0;font:inherit;font-family:var(--font-mono);color:var(--accent-ink);cursor:pointer}
.gr-idbtn:hover{text-decoration:underline}
`;
    document.head.appendChild(s);
  }

  const W = 1000, H = 560;
  // W×H was calibrated for a ~152-node graph. Force layout needs area to grow
  // with the node count (Fruchterman-Reingold: ideal spacing = sqrt(area/N)),
  // otherwise repulsion cannot separate the nodes and they stay clamped in one
  // block. The simulation space scales; the viewport does not.
  const LAYOUT_BASE_NODES = 152;
  const LAYOUT_ELLIPSE_RX_RATIO = 0.3;
  const LAYOUT_ELLIPSE_RY_RATIO = 0.295;
  let layoutW = W, layoutH = H, layoutScale = 1;

  function resizeLayoutSpace(nodeCount) {
    const scale = Math.max(1, Math.sqrt(nodeCount / LAYOUT_BASE_NODES));
    layoutW = Math.round(W * scale);
    layoutH = Math.round(H * scale);
    layoutScale = scale;
  }

  const SEED = 987654321;

  const IMP_MIN = 0.30, IMP_MAX = 0.93;
  const CONF_MIN = 0.30, CONF_MAX = 0.95;
  const MIN_R = 5, MAX_R = 22;

  const MIN_ZOOM = 0.35, MAX_ZOOM = 4;
  const ZOOM_STEP = 1.15;
  const LABEL_ZOOM_THRESHOLD = 1.6;
  const LABEL_TOP_DEGREE_COUNT = 18;
  const LABEL_FONT_BASE = 8.5;
  const LABEL_GAP = 11;

  const MAX_FIT_ZOOM = 2.5;
  const FIT_ZOOM_FLOOR = 0.05;
  const FIT_PADDING = 48;
  const FIT_DURATION_MS = 260;
  const MIN_VISIBLE_FRACTION = 0.25;
  const BBOX_LABEL_PADDING = 26;

  const REPULSION_STRENGTH = 5200;
  const REPULSION_GRID_THRESHOLD = 300;
  const GRID_CELL_SIZE = 90;
  const SPRING_LENGTH = 82;
  const SPRING_K_BASE = 0.045;
  const SPRING_MAX_DELTA = 130;
  const CLUSTER_STRENGTH = 0.028;
  const CENTER_STRENGTH = 0.026;
  const DAMPING = 0.86;
  const MAX_SPEED = 34;
  const ALPHA_START = 1;
  const ALPHA_DECAY = 0.985;
  const ALPHA_MIN = 0.01;
  const MAX_TICKS = 400;

  const TYPE_COLOR = { decision: "#1f9e6f", lesson: "#d9720f" };
  const TYPE_SHAPE = { decision: "circle", lesson: "diamond" };
  const UNEXPECTED_COLOR = "var(--accent-ink)";
  const LABEL_TEXT_COLOR = "var(--txt-hi)";
  const LEGEND_RING_NEUTRAL = "var(--dim)";
  const FOCUS_RING_COLOR = "var(--txt-hi)";
  const CLUSTER_NEUTRAL_COLOR = "var(--faint)";

  const STATUS_RING = {
    accepted: { dash: "0", opacity: 0.95, color: null, width: 1.7 },
    proposed: { dash: "3 3", opacity: 0.45, color: null, width: 1.4 },
    reverted: { dash: "0", opacity: 1, color: "var(--st-reverted)", width: 2.3 },
    superseded: { dash: "2 2", opacity: 0.9, color: "var(--st-superseded)", width: 2.1 },
  };

  const EDGE_DASH = {
    conceptually_related_to: "0",
    semantically_similar_to: "1 4",
    rationale_for: "6 3",
    shares_data_with: "9 3 2 3",
  };
  const EDGE_MIN_W = 0.8, EDGE_MAX_W = 2.6;
  const EDGE_MIN_OP = 0.75, EDGE_MAX_OP = 1;
  const EDGE_TYPE_ORDER = Object.keys(EDGE_DASH);
  const STATUS_ORDER = Object.keys(STATUS_RING);
  const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

  const EDGE_TYPE_I18N = {
    conceptually_related_to: ["ui.graph.edge_conceptually_related_to", "Conceptually related"],
    semantically_similar_to: ["ui.graph.edge_semantically_similar_to", "Semantically similar"],
    rationale_for: ["ui.graph.edge_rationale_for", "Rationale for"],
    shares_data_with: ["ui.graph.edge_shares_data_with", "Shares data with"],
  };
  const STATUS_I18N = {
    accepted: {
      label: ["ui.graph.status_accepted", "Accepted"],
      style: ["ui.graph.status_accepted_style", "solid ring"],
    },
    proposed: {
      label: ["ui.graph.status_proposed", "Proposed"],
      style: ["ui.graph.status_proposed_style", "dashed ring"],
    },
    reverted: {
      label: ["ui.graph.status_reverted", "Reverted"],
      style: ["ui.graph.status_reverted_style", "thick ring"],
    },
    superseded: {
      label: ["ui.graph.status_superseded", "Superseded"],
      style: ["ui.graph.status_superseded_style", "dashed muted ring"],
    },
  };

  const DIM_OPACITY = 0.22;
  const SECOND_DEGREE_OPACITY = 0.55;
  const CLUSTER_TOP_COUNT = 10;
  const FOCUS_DURATION_MS = 300;
  const DRAG_CLICK_THRESHOLD = 3;
  const CLUSTER_HALO_WIDTH = 2.2;
  const CLUSTER_HALO_MARGIN = 6;

  function makeRng(seed) {
    let s = seed % 2147483647;
    if (s <= 0) s += 2147483646;
    return function rng() {
      s = (s * 16807) % 2147483647;
      return (s - 1) / 2147483646;
    };
  }

  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

  function computeBoundingBox(nodes, posById, radiusFn, labelPadding) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach((n) => {
      const p = posById[n.id];
      if (!p) return;
      const r = radiusFn(n) + labelPadding;
      if (p.x - r < minX) minX = p.x - r;
      if (p.x + r > maxX) maxX = p.x + r;
      if (p.y - r < minY) minY = p.y - r;
      if (p.y + r > maxY) maxY = p.y + r;
    });
    if (!isFinite(minX) || !isFinite(minY)) return null;
    return { minX, minY, maxX, maxY };
  }

  function computeFitView(bbox, viewport, padding) {
    const vw = (viewport && viewport.width) || W;
    const vh = (viewport && viewport.height) || H;
    if (!bbox) return { zoom: 1, x: 0, y: 0 };
    const bw = Math.max(bbox.maxX - bbox.minX, 1e-6);
    const bh = Math.max(bbox.maxY - bbox.minY, 1e-6);
    const availW = Math.max(vw - padding * 2, 1e-6);
    const availH = Math.max(vh - padding * 2, 1e-6);
    const rawZoom = Math.min(availW / bw, availH / bh);
    const zoom = clamp(rawZoom, FIT_ZOOM_FLOOR, MAX_FIT_ZOOM);
    const cx = (bbox.minX + bbox.maxX) / 2;
    const cy = (bbox.minY + bbox.maxY) / 2;
    return { zoom, x: vw / 2 - cx * zoom, y: vh / 2 - cy * zoom };
  }

  function clampPanToBounds(view, bbox, viewport, minVisibleFraction) {
    if (!bbox) return { x: view.x, y: view.y };
    const vw = (viewport && viewport.width) || W;
    const vh = (viewport && viewport.height) || H;
    const zoom = view.zoom;
    const bw = (bbox.maxX - bbox.minX) * zoom;
    const bh = (bbox.maxY - bbox.minY) * zoom;
    const minVisW = bw * minVisibleFraction;
    const minVisH = bh * minVisibleFraction;
    const xMin = minVisW - bbox.maxX * zoom;
    const xMax = vw - minVisW - bbox.minX * zoom;
    const yMin = minVisH - bbox.maxY * zoom;
    const yMax = vh - minVisH - bbox.minY * zoom;
    return {
      x: xMin <= xMax ? clamp(view.x, xMin, xMax) : view.x,
      y: yMin <= yMax ? clamp(view.y, yMin, yMax) : view.y,
    };
  }

  function getViewportSize(svgEl) {
    if (svgEl && svgEl.viewBox && svgEl.viewBox.baseVal && svgEl.viewBox.baseVal.width && svgEl.viewBox.baseVal.height) {
      return { width: svgEl.viewBox.baseVal.width, height: svgEl.viewBox.baseVal.height };
    }
    if (svgEl && svgEl.getBoundingClientRect) {
      const rect = svgEl.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) return { width: rect.width, height: rect.height };
    }
    return { width: W, height: H };
  }

  function prefersReducedMotion() {
    return typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(REDUCED_MOTION_QUERY).matches;
  }

  function scaleLinear(v, inMin, inMax, outMin, outMax) {
    const t = clamp((v - inMin) / (inMax - inMin || 1), 0, 1);
    return outMin + t * (outMax - outMin);
  }

  function radiusForImp(imp) { return scaleLinear(imp, IMP_MIN, IMP_MAX, MIN_R, MAX_R); }
  function edgeWidthForConf(conf) { return scaleLinear(conf, CONF_MIN, CONF_MAX, EDGE_MIN_W, EDGE_MAX_W); }
  function edgeOpacityForConf(conf) { return scaleLinear(conf, CONF_MIN, CONF_MAX, EDGE_MIN_OP, EDGE_MAX_OP); }

  function matchesQueryNode(n, q) {
    if (!q) return false;
    return n.id.toLowerCase().includes(q) || (n.title || "").toLowerCase().includes(q) || (n.project || "").toLowerCase().includes(q);
  }

  function neighborRowsFor(id, edges) {
    return edges
      .filter((e) => e.from === id || e.to === id)
      .map((e) => ({ id: e.from === id ? e.to : e.from, type: e.type, conf: e.conf }));
  }

  function edgeTypeLabel(type) {
    const entry = EDGE_TYPE_I18N[type];
    if (!entry) return type;
    return t(...entry);
  }

  function clusterSwatchColor(rank, color) {
    return rank < CLUSTER_TOP_COUNT ? color : CLUSTER_NEUTRAL_COLOR;
  }

  function statusFilterGroup(status) {
    if (status === "accepted") return "accepted";
    if (status === "proposed") return "proposed";
    return "other";
  }

  function computeNodeVisualState({ n, focalId, neighborSet, secondDegreeIds, query, activeCluster, matchesQuery }) {
    const hasQuery = !!query.trim();
    if (hasQuery) {
      if (matchesQuery(n)) return "focus";
      if (focalId && (n.id === focalId || (neighborSet && neighborSet.has(n.id)))) return "second";
      if (focalId && secondDegreeIds && secondDegreeIds.has(n.id)) return "second";
      return "dim";
    }
    if (focalId) {
      if (n.id === focalId || (neighborSet && neighborSet.has(n.id))) return "focus";
      if (secondDegreeIds && secondDegreeIds.has(n.id)) return "second";
      return "dim";
    }
    if (activeCluster) return n.cluster === activeCluster ? "focus" : "dim";
    return "normal";
  }

  function buildInitialLayout(PM) {
    resizeLayoutSpace(PM.nodes.length);
    const rng = makeRng(SEED);
    const pos = {};
    const cx0 = layoutW / 2, cy0 = layoutH / 2;
    const rx = layoutW * LAYOUT_ELLIPSE_RX_RATIO, ry = layoutH * LAYOUT_ELLIPSE_RY_RATIO;
    const byCluster = {};
    PM.nodes.forEach((n) => { (byCluster[n.cluster] = byCluster[n.cluster] || []).push(n); });
    const clusterCount = PM.clusters.length || 1;
    PM.clusters.forEach((c, ci) => {
      const ang = (ci / clusterCount) * Math.PI * 2 - Math.PI / 2;
      const cx = cx0 + Math.cos(ang) * rx;
      const cy = cy0 + Math.sin(ang) * ry;
      (byCluster[c.id] || []).forEach((n) => {
        const jr = 16 + rng() * 50;
        const jt = rng() * Math.PI * 2;
        pos[n.id] = { x: cx + Math.cos(jt) * jr, y: cy + Math.sin(jt) * jr, vx: 0, vy: 0, cluster: n.cluster };
      });
    });
    PM.nodes.forEach((n) => {
      if (!pos[n.id]) {
        pos[n.id] = { x: cx0 + (rng() - 0.5) * 100, y: cy0 + (rng() - 0.5) * 100, vx: 0, vy: 0, cluster: n.cluster };
      }
    });
    return pos;
  }

  function repelPair(a, b, rng, scale) {
    let dx = a.x - b.x, dy = a.y - b.y;
    let d2 = dx * dx + dy * dy;
    if (d2 < 1) { dx = rng() - 0.5; dy = rng() - 0.5; d2 = dx * dx + dy * dy || 0.01; }
    const d = Math.sqrt(d2);
    const f = (REPULSION_STRENGTH / d2) * scale;
    const fx = (dx / d) * f, fy = (dy / d) * f;
    a.vx += fx; a.vy += fy;
    b.vx -= fx; b.vy -= fy;
  }

  function applyRepulsionBrute(nodes, rng) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) repelPair(nodes[i], nodes[j], rng, 1);
    }
  }

  function buildGrid(nodes, cellSize) {
    const grid = new Map();
    nodes.forEach((n) => {
      const key = Math.floor(n.x / cellSize) + "," + Math.floor(n.y / cellSize);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(n);
    });
    return grid;
  }

  function applyRepulsionGrid(nodes, cellSize, rng) {
    const grid = buildGrid(nodes, cellSize);
    nodes.forEach((n) => {
      const gx = Math.floor(n.x / cellSize), gy = Math.floor(n.y / cellSize);
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const bucket = grid.get((gx + dx) + "," + (gy + dy));
          if (!bucket) continue;
          bucket.forEach((other) => { if (other !== n) repelPair(n, other, rng, 0.5); });
        }
      }
    });
  }

  function applyAttraction(byId, edges) {
    edges.forEach((e) => {
      const a = byId[e.from], b = byId[e.to];
      if (!a || !b) return;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const k = SPRING_K_BASE * (0.4 + e.conf);
      const targetLen = SPRING_LENGTH * (1 - 0.35 * e.conf);
      const f = k * clamp(d - targetLen, -SPRING_MAX_DELTA, SPRING_MAX_DELTA);
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    });
  }

  function applyClusterGravity(nodes) {
    const sum = {}, count = {};
    nodes.forEach((n) => {
      if (!sum[n.cluster]) { sum[n.cluster] = { x: 0, y: 0 }; count[n.cluster] = 0; }
      sum[n.cluster].x += n.x; sum[n.cluster].y += n.y; count[n.cluster] += 1;
    });
    nodes.forEach((n) => {
      const cx = sum[n.cluster].x / count[n.cluster], cy = sum[n.cluster].y / count[n.cluster];
      n.vx += (cx - n.x) * CLUSTER_STRENGTH;
      n.vy += (cy - n.y) * CLUSTER_STRENGTH;
    });
  }

  function applyCenterGravity(nodes) {
    // Gravity fights repulsion, so a fixed pull packs every graph into the same
    // radius no matter how many nodes it holds. Radius settles as
    // (repulsion/gravity)^(1/3), so the pull has to fall off faster than the
    // node count grows for the disc to stay uncrowded — dividing by scale alone
    // still left the nodes overlapping at ~4k nodes.
    const strength = CENTER_STRENGTH / (layoutScale * layoutScale);
    nodes.forEach((n) => {
      n.vx += (layoutW / 2 - n.x) * strength;
      n.vy += (layoutH / 2 - n.y) * strength;
    });
  }

  function capVelocity(nodes, maxSpeed) {
    nodes.forEach((n) => {
      const s2 = n.vx * n.vx + n.vy * n.vy;
      const max2 = maxSpeed * maxSpeed;
      if (s2 > max2) {
        const s = Math.sqrt(s2);
        n.vx = (n.vx / s) * maxSpeed;
        n.vy = (n.vy / s) * maxSpeed;
      }
    });
  }

  function integrateNodes(nodes, alpha) {
    nodes.forEach((n) => {
      n.vx *= DAMPING; n.vy *= DAMPING;
      n.x += n.vx * alpha;
      n.y += n.vy * alpha;
      // No bounding box: repulsion and springs settle their own spacing, and
      // the fit pass frames whatever extent they reach. Clamping to a fixed
      // box only compresses dense graphs into a block.
    });
  }

  function simulationTick(nodes, edges, byId, alpha, rng) {
    if (nodes.length > REPULSION_GRID_THRESHOLD) applyRepulsionGrid(nodes, GRID_CELL_SIZE, rng);
    else applyRepulsionBrute(nodes, rng);
    applyAttraction(byId, edges);
    applyClusterGravity(nodes);
    applyCenterGravity(nodes);
    capVelocity(nodes, MAX_SPEED);
    integrateNodes(nodes, alpha);
  }

  function NodeShape({ kind, r, fill, stroke, strokeWidth, strokeDasharray, strokeOpacity }) {
    const common = { fill, stroke, strokeWidth, strokeDasharray, strokeOpacity };
    if ((TYPE_SHAPE[kind] || "circle") === "diamond") {
      return <polygon points={`0,${-r} ${r},0 0,${r} ${-r},0`} {...common} />;
    }
    return <circle r={r} {...common} />;
  }

  function GraphView({ nav, statuses }) {
    const PM = window.PM;
    const [hover, setHover] = useState(null);
    const [tip, setTip] = useState(null);
    const [selectedId, setSelectedId] = useState(null);
    const [activeCluster, setActiveCluster] = useState(null);
    const [clustersExpanded, setClustersExpanded] = useState(false);
    const [showUnexp, setShowUnexp] = useState(true);
    const [query, setQuery] = useState("");
    const [filterTypes, setFilterTypes] = useState(() => new Set());
    const [filterStatuses, setFilterStatuses] = useState(() => new Set());
    const [filterProject, setFilterProject] = useState("");
    const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
    const [isDragging, setIsDragging] = useState(false);
    const [settled, setSettled] = useState(false);
    const [showTable, setShowTable] = useState(false);
    const [bbox, setBbox] = useState(null);
    const [viewSize, setViewSize] = useState({ w: W, h: H });

    const svgRef = useRef(null);
    const canvasElRef = useRef(null);
    const onWheelRef = useRef(null);
    const nodeElRefs = useRef({});
    const edgeElRefs = useRef([]);
    const posRef = useRef(null);
    const focusAnimRef = useRef(null);
    const fitAnimRef = useRef(null);
    const minZoomRef = useRef(MIN_ZOOM);
    const viewRef = useRef(view);
    const reducedMotionRef = useRef(prefersReducedMotion());
    viewRef.current = view;
    if (posRef.current === null) posRef.current = buildInitialLayout(PM);

    useEffect(() => {
      const nodesArr = PM.nodes.map((n) => posRef.current[n.id]);
      const byId = posRef.current;
      const rng = makeRng(SEED + 1);

      function paintPositions() {
        PM.nodes.forEach((n) => {
          const el = nodeElRefs.current[n.id];
          const p = byId[n.id];
          if (el && p) el.setAttribute("transform", `translate(${p.x.toFixed(2)},${p.y.toFixed(2)})`);
        });
        PM.edges.forEach((e, i) => {
          const el = edgeElRefs.current[i];
          if (!el) return;
          const a = byId[e.from], b = byId[e.to];
          if (!a || !b) return;
          el.setAttribute("x1", a.x.toFixed(2)); el.setAttribute("y1", a.y.toFixed(2));
          el.setAttribute("x2", b.x.toFixed(2)); el.setAttribute("y2", b.y.toFixed(2));
        });
      }

      if (reducedMotionRef.current) {
        let alpha = ALPHA_START;
        let tick = 0;
        while (alpha >= ALPHA_MIN && tick < MAX_TICKS) {
          tick += 1;
          alpha *= ALPHA_DECAY;
          simulationTick(nodesArr, PM.edges, byId, alpha, rng);
        }
        paintPositions();
        setSettled(true);
        return undefined;
      }

      let alpha = ALPHA_START;
      let tick = 0;
      let raf = null;

      function frame() {
        if (alpha < ALPHA_MIN || tick >= MAX_TICKS) {
          setSettled(true);
          raf = null;
          return;
        }
        tick += 1;
        alpha *= ALPHA_DECAY;
        simulationTick(nodesArr, PM.edges, byId, alpha, rng);
        paintPositions();
        raf = requestAnimationFrame(frame);
      }
      raf = requestAnimationFrame(frame);
      return () => { if (raf) cancelAnimationFrame(raf); };
    }, []);

    const neighbors = useMemo(() => {
      const m = {};
      PM.edges.forEach((e) => {
        (m[e.from] = m[e.from] || new Set()).add(e.to);
        (m[e.to] = m[e.to] || new Set()).add(e.from);
      });
      return m;
    }, []);

    const topDegreeIds = useMemo(() => {
      const sorted = PM.nodes.slice().sort((a, b) => {
        const da = neighbors[a.id] ? neighbors[a.id].size : 0;
        const db = neighbors[b.id] ? neighbors[b.id].size : 0;
        return db - da;
      });
      return new Set(sorted.slice(0, LABEL_TOP_DEGREE_COUNT).map((n) => n.id));
    }, []);

    const focalId = hover || selectedId || null;
    const neighborSet = focalId ? (neighbors[focalId] || new Set()) : null;

    const secondDegreeIds = useMemo(() => {
      if (!selectedId || hover) return null;
      const first = neighbors[selectedId] || new Set();
      const second = new Set();
      first.forEach((id) => {
        (neighbors[id] || new Set()).forEach((nb) => {
          if (nb !== selectedId && !first.has(nb)) second.add(nb);
        });
      });
      return second;
    }, [selectedId, hover, neighbors]);

    const q = query.trim().toLowerCase();
    const matchesQuery = (n) => matchesQueryNode(n, q);
    const searchMatches = useMemo(() => (q ? PM.nodes.filter((n) => matchesQueryNode(n, q)) : []), [q]);

    const clusterCounts = useMemo(() => {
      const m = {};
      PM.nodes.forEach((n) => { m[n.cluster] = (m[n.cluster] || 0) + 1; });
      return m;
    }, []);
    const sortedClusters = useMemo(
      () => PM.clusters.slice().sort((a, b) => (clusterCounts[b.id] || 0) - (clusterCounts[a.id] || 0)),
      [clusterCounts]
    );
    const clusterColorById = useMemo(
      () => Object.fromEntries(PM.clusters.map((c) => [c.id, c.color])),
      []
    );
    const visibleClusterList = clustersExpanded ? sortedClusters : sortedClusters.slice(0, CLUSTER_TOP_COUNT);
    const hiddenClusterCount = Math.max(0, sortedClusters.length - CLUSTER_TOP_COUNT);

    const visibleNodes = useMemo(() => {
      return PM.nodes.filter((n) => {
        if (filterTypes.size && !filterTypes.has(n.kind === "lesson" ? "lesson" : "decision")) return false;
        if (filterStatuses.size) {
          const st = statuses[n.id] || n.status;
          if (!filterStatuses.has(statusFilterGroup(st))) return false;
        }
        if (filterProject && n.project !== filterProject) return false;
        return true;
      });
    }, [filterTypes, filterStatuses, filterProject, statuses]);
    const visibleIdSet = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
    const activeFilterCount = filterTypes.size + filterStatuses.size + (filterProject ? 1 : 0);

    useEffect(() => {
      if (selectedId && !visibleIdSet.has(selectedId)) setSelectedId(null);
    }, [visibleIdSet, selectedId]);

    useEffect(() => {
      const el = svgRef.current;
      if (!el || typeof ResizeObserver === "undefined") return undefined;
      const sync = () => {
        const rect = el.getBoundingClientRect();
        if (rect.width < 1 || rect.height < 1) return;
        setViewSize((prev) => {
          const w = Math.round(rect.width);
          const h = Math.round(rect.height);
          if (prev.w === w && prev.h === h) return prev;
          return { w, h };
        });
      };
      sync();
      const observer = new ResizeObserver(sync);
      observer.observe(el);
      return () => observer.disconnect();
    }, []);

    useEffect(() => {
      if (!settled) return undefined;
      const nextBBox = computeBoundingBox(visibleNodes, posRef.current, (n) => radiusForImp(n.imp), BBOX_LABEL_PADDING);
      setBbox(nextBBox);
      const viewport = getViewportSize(svgRef.current);
      const fit = computeFitView(nextBBox, viewport, FIT_PADDING);
      minZoomRef.current = Math.min(MIN_ZOOM, fit.zoom * 0.5);
      runFitTransition(fit);
      return undefined;
    }, [settled, visibleIdSet, viewSize]);

    const neighborRows = useMemo(
      () => (selectedId ? neighborRowsFor(selectedId, PM.edges) : []),
      [selectedId]
    );

    const toggleTypeFilter = (kind) => setFilterTypes((s) => {
      const n = new Set(s);
      if (n.has(kind)) n.delete(kind); else n.add(kind);
      return n;
    });
    const toggleStatusFilter = (group) => setFilterStatuses((s) => {
      const n = new Set(s);
      if (n.has(group)) n.delete(group); else n.add(group);
      return n;
    });
    const clearFilters = () => {
      setFilterTypes(new Set());
      setFilterStatuses(new Set());
      setFilterProject("");
    };

    function runFitTransition(target) {
      if (fitAnimRef.current) { cancelAnimationFrame(fitAnimRef.current); fitAnimRef.current = null; }
      if (reducedMotionRef.current) { setView(target); return; }
      const startView = viewRef.current;
      const t0 = performance.now();
      const step = (now) => {
        const t = clamp((now - t0) / FIT_DURATION_MS, 0, 1);
        const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        setView({
          zoom: startView.zoom + (target.zoom - startView.zoom) * ease,
          x: startView.x + (target.x - startView.x) * ease,
          y: startView.y + (target.y - startView.y) * ease,
        });
        if (t < 1) fitAnimRef.current = requestAnimationFrame(step);
        else fitAnimRef.current = null;
      };
      fitAnimRef.current = requestAnimationFrame(step);
    }

    function focusNode(id) {
      setSelectedId(id);
      setActiveCluster(null);
      const p = posRef.current[id];
      if (!p) return;
      if (focusAnimRef.current) cancelAnimationFrame(focusAnimRef.current);
      const startView = viewRef.current;
      const targetZoom = Math.max(startView.zoom, 1);
      const targetX = viewSize.w / 2 - p.x * targetZoom;
      const targetY = viewSize.h / 2 - p.y * targetZoom;
      if (reducedMotionRef.current) {
        setView({ zoom: targetZoom, x: targetX, y: targetY });
        return;
      }
      const t0 = performance.now();
      const step = (now) => {
        const t = clamp((now - t0) / FOCUS_DURATION_MS, 0, 1);
        const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        setView({
          zoom: startView.zoom + (targetZoom - startView.zoom) * ease,
          x: startView.x + (targetX - startView.x) * ease,
          y: startView.y + (targetY - startView.y) * ease,
        });
        if (t < 1) focusAnimRef.current = requestAnimationFrame(step);
        else focusAnimRef.current = null;
      };
      focusAnimRef.current = requestAnimationFrame(step);
    }

    function resetAll() {
      if (focusAnimRef.current) { cancelAnimationFrame(focusAnimRef.current); focusAnimRef.current = null; }
      setSelectedId(null);
      setHover(null);
      setActiveCluster(null);
      setQuery("");
      clearFilters();
      const fullBBox = computeBoundingBox(PM.nodes, posRef.current, (n) => radiusForImp(n.imp), BBOX_LABEL_PADDING);
      const viewport = getViewportSize(svgRef.current);
      const fit = computeFitView(fullBBox, viewport, FIT_PADDING);
      minZoomRef.current = Math.min(MIN_ZOOM, fit.zoom * 0.5);
      runFitTransition(fit);
    }

    const onClusterClick = (id) => {
      setSelectedId(null);
      setActiveCluster((a) => (a === id ? null : id));
    };

    const onSearchKeyDown = (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (searchMatches.length) focusNode(searchMatches[0].id);
      }
    };

    useEffect(() => {
      const onKeyDown = (ev) => {
        if (ev.key !== "Escape") return;
        setSelectedId(null);
        setQuery("");
      };
      window.addEventListener("keydown", onKeyDown);
      return () => window.removeEventListener("keydown", onKeyDown);
    }, []);

    useEffect(() => () => {
      if (focusAnimRef.current) cancelAnimationFrame(focusAnimRef.current);
      if (fitAnimRef.current) cancelAnimationFrame(fitAnimRef.current);
    }, []);

    const toSvgPoint = (clientX, clientY) => {
      const svgEl = svgRef.current;
      if (!svgEl || !svgEl.createSVGPoint) return { x: clientX, y: clientY };
      const pt = svgEl.createSVGPoint();
      pt.x = clientX; pt.y = clientY;
      const ctm = svgEl.getScreenCTM();
      if (!ctm) return { x: clientX, y: clientY };
      const p = pt.matrixTransform(ctm.inverse());
      return { x: p.x, y: p.y };
    };

    const onWheel = (ev) => {
      ev.preventDefault();
      const p = toSvgPoint(ev.clientX, ev.clientY);
      setView((v) => {
        const dir = ev.deltaY < 0 ? 1 : -1;
        const nz = clamp(v.zoom * Math.pow(ZOOM_STEP, dir), minZoomRef.current, MAX_ZOOM);
        const nx = p.x - ((p.x - v.x) / v.zoom) * nz;
        const ny = p.y - ((p.y - v.y) / v.zoom) * nz;
        const clamped = clampPanToBounds({ zoom: nz, x: nx, y: ny }, bbox, { width: W, height: H }, MIN_VISIBLE_FRACTION);
        return { zoom: nz, x: clamped.x, y: clamped.y };
      });
    };
    onWheelRef.current = onWheel;

    useEffect(() => {
      if (showTable) return undefined;
      const el = canvasElRef.current;
      if (!el) return undefined;
      const handleWheel = (ev) => onWheelRef.current(ev);
      el.addEventListener("wheel", handleWheel, { passive: false });
      return () => el.removeEventListener("wheel", handleWheel);
    }, [showTable]);

    const onCanvasMouseDown = (ev) => {
      if (ev.button !== 0) return;
      if (ev.target.closest && ev.target.closest(".gr-node")) return;
      const startClientX = ev.clientX, startClientY = ev.clientY;
      const startSvg = toSvgPoint(ev.clientX, ev.clientY);
      const startView = view;
      let dragged = false;
      setIsDragging(true);
      const onMove = (mv) => {
        if (Math.abs(mv.clientX - startClientX) > DRAG_CLICK_THRESHOLD || Math.abs(mv.clientY - startClientY) > DRAG_CLICK_THRESHOLD) dragged = true;
        const cur = toSvgPoint(mv.clientX, mv.clientY);
        const nx = startView.x + (cur.x - startSvg.x);
        const ny = startView.y + (cur.y - startSvg.y);
        const clamped = clampPanToBounds({ zoom: startView.zoom, x: nx, y: ny }, bbox, { width: W, height: H }, MIN_VISIBLE_FRACTION);
        setView({ zoom: startView.zoom, x: clamped.x, y: clamped.y });
      };
      const onUp = () => {
        setIsDragging(false);
        if (!dragged) setSelectedId(null);
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    };

    const onCanvasDoubleClick = () => {
      const viewport = getViewportSize(svgRef.current);
      const fit = computeFitView(bbox, viewport, FIT_PADDING);
      minZoomRef.current = Math.min(MIN_ZOOM, fit.zoom * 0.5);
      runFitTransition(fit);
    };

    const nodeVisualState = (n) => computeNodeVisualState({ n, focalId, neighborSet, secondDegreeIds, query, activeCluster, matchesQuery });

    const unexpected = PM.edges.filter((e) => e.unexpected);
    const isolatedCount = PM.nodes.filter((n) => !neighbors[n.id] || neighbors[n.id].size === 0).length;
    const showAllLabels = view.zoom > LABEL_ZOOM_THRESHOLD;

    return (
      <div className="pm-page fade-in">
        <div style={{ display: "flex", alignItems: "flex-end", gap: 14 }}>
          <div style={{ flexShrink: 0 }}>
            <div className="pm-eyebrow">{t("ui.graph.eyebrow", "Cross-project knowledge graph")}</div>
            <h1 className="pm-h" style={{ marginTop: 6 }}>{t("ui.graph.heading", "Graph")}</h1>
          </div>
          <div style={{ flex: 1 }} />
          <button className={"pm-btn sm" + (showTable ? " accent" : "")} onClick={() => setShowTable((v) => !v)} aria-pressed={showTable}>
            <Icon name="queue" size={14} /> {showTable ? t("ui.graph.table_toggle_hide", "Graph view") : t("ui.graph.table_toggle_show", "Table view")}
          </button>
          <button className={"pm-btn sm" + (showUnexp ? " accent" : "")} onClick={() => setShowUnexp((v) => !v)}>
            <Icon name="spark" size={14} /> {t("ui.graph.unexpected_links", "Unexpected links")}
          </button>
          <button className="pm-btn sm ghost" onClick={resetAll}>
            <Icon name="revert" size={14} /> {t("ui.graph.reset", "Reset")}
          </button>
        </div>

        <div className="gr-toolbar">
          <label htmlFor="gr-search-input" className="gr-vh">{t("ui.graph.search_label", "Search graph nodes by id, title or project")}</label>
          <div className="pm-search gr-search">
            <Icon name="search" size={14} />
            <input id="gr-search-input" placeholder={t("ui.graph.search_placeholder", "Search nodes…")} value={query}
              onChange={(ev) => setQuery(ev.target.value)}
              onKeyDown={onSearchKeyDown} />
          </div>
          {q && (
            <span className="gr-matchcount">
              {searchMatches.length} {searchMatches.length === 1
                ? t("ui.graph.match_one", "match")
                : t("ui.graph.match_many", "matches")}
            </span>
          )}

          <div className="gr-chips">
            <button className={"gr-chip" + (filterTypes.has("decision") ? " on" : "")} onClick={() => toggleTypeFilter("decision")}>{t("ui.graph.chip_decision", "Decision")}</button>
            <button className={"gr-chip" + (filterTypes.has("lesson") ? " on" : "")} onClick={() => toggleTypeFilter("lesson")}>{t("ui.graph.chip_lesson", "Lesson")}</button>
          </div>
          <div className="gr-chips">
            <button className={"gr-chip" + (filterStatuses.has("accepted") ? " on" : "")} onClick={() => toggleStatusFilter("accepted")}>{t("ui.graph.chip_accepted", "Accepted")}</button>
            <button className={"gr-chip" + (filterStatuses.has("proposed") ? " on" : "")} onClick={() => toggleStatusFilter("proposed")}>{t("ui.graph.chip_proposed", "Proposed")}</button>
            <button className={"gr-chip" + (filterStatuses.has("other") ? " on" : "")} onClick={() => toggleStatusFilter("other")}>{t("ui.graph.chip_other", "Other")}</button>
          </div>
          <select className="gr-select" aria-label={t("ui.graph.project_filter_label", "Filter by project")} value={filterProject} onChange={(ev) => setFilterProject(ev.target.value)}>
            <option value="">{t("ui.graph.all_projects", "All projects")}</option>
            {PM.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {activeFilterCount > 0 && (
            <span className="gr-filtercount">
              {activeFilterCount} {t("ui.graph.active_filters", "active")}
              <button className="pm-btn ghost sm" onClick={clearFilters}>{t("ui.graph.clear", "Clear")}</button>
            </span>
          )}
        </div>

        <div className="gr-wrap">
          {showTable ? (
            <GraphTable nodes={visibleNodes} neighbors={neighbors} statuses={statuses} nav={nav} />
          ) : (
          <div className={"gr-canvas" + (isDragging ? " dragging" : "")}
            ref={canvasElRef}
            onMouseLeave={() => { setHover(null); setTip(null); }}
            onMouseDown={onCanvasMouseDown}
            onDoubleClick={onCanvasDoubleClick}>
            <svg ref={svgRef} viewBox={`0 0 ${viewSize.w} ${viewSize.h}`} preserveAspectRatio="xMidYMid meet">
              <defs>
                <filter id="gr-glow" x="-60%" y="-60%" width="220%" height="220%">
                  <feGaussianBlur stdDeviation="3.2" result="gr-blur" />
                  <feMerge>
                    <feMergeNode in="gr-blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
                <pattern id="gr-mesh-pattern" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M40 0H0V40" fill="none" stroke="var(--line2)" strokeWidth="1" />
                </pattern>
              </defs>
              <rect className="gr-mesh" width={viewSize.w} height={viewSize.h} fill="url(#gr-mesh-pattern)" opacity="0.045" />
              <g transform={`translate(${view.x},${view.y}) scale(${view.zoom})`}>
                {PM.edges.map((e, i) => {
                  const a = posRef.current[e.from], b = posRef.current[e.to];
                  if (!a || !b) return null;
                  if (e.unexpected && !showUnexp) return null;
                  if (!visibleIdSet.has(e.from) || !visibleIdSet.has(e.to)) return null;
                  const act = focalId && (e.from === focalId || e.to === focalId);
                  const dimmed = focalId
                    ? !act
                    : (activeCluster && a.cluster !== activeCluster && b.cluster !== activeCluster);
                  const dash = e.unexpected ? "6 4" : (EDGE_DASH[e.type] || "0");
                  const width = e.unexpected ? 2.4 : (act ? edgeWidthForConf(e.conf) + 0.8 : edgeWidthForConf(e.conf));
                  const opacity = dimmed ? 0.1 : (e.unexpected ? 0.95 : (act ? Math.min(1, edgeOpacityForConf(e.conf) + 0.25) : edgeOpacityForConf(e.conf)));
                  return (
                    <line key={i}
                      ref={(el) => { edgeElRefs.current[i] = el; }}
                      x1={a.x.toFixed(2)} y1={a.y.toFixed(2)} x2={b.x.toFixed(2)} y2={b.y.toFixed(2)}
                      stroke={e.unexpected ? UNEXPECTED_COLOR : (act ? FOCUS_RING_COLOR : "var(--dim)")}
                      strokeWidth={width}
                      strokeDasharray={dash}
                      strokeOpacity={opacity}
                      className={e.unexpected ? "gr-edge-unexp" : undefined}
                      filter={e.unexpected ? "url(#gr-glow)" : undefined} />
                  );
                })}
                {PM.nodes.map((n) => {
                  if (!visibleIdSet.has(n.id)) return null;
                  const p0 = posRef.current[n.id] || { x: layoutW / 2, y: layoutH / 2 };
                  const st = statuses[n.id] || n.status;
                  const typeKey = n.kind === "lesson" ? "lesson" : "decision";
                  const col = TYPE_COLOR[typeKey];
                  const ring = STATUS_RING[st] || STATUS_RING.accepted;
                  const r = radiusForImp(n.imp);
                  const vstate = nodeVisualState(n);
                  const opacity = vstate === "dim" ? DIM_OPACITY : (vstate === "second" ? SECOND_DEGREE_OPACITY : 1);
                  const isHover = hover === n.id;
                  const isSelected = selectedId === n.id;
                  const isSearchMatch = q && matchesQuery(n);
                  const isHalo = activeCluster && n.cluster === activeCluster;
                  const showLabel = showAllLabels || topDegreeIds.has(n.id) || isHover || isSelected || matchesQuery(n);
                  return (
                    <g key={n.id} className="gr-node"
                      ref={(el) => { nodeElRefs.current[n.id] = el; }}
                      transform={`translate(${p0.x.toFixed(2)},${p0.y.toFixed(2)})`}
                      style={(isHover || isSelected || isSearchMatch) ? { filter: "url(#gr-glow)" } : undefined}
                      onMouseEnter={() => setHover(n.id)}
                      onMouseLeave={() => setHover(null)}
                      onMouseMove={(ev) => {
                        const rect = ev.currentTarget.closest(".gr-canvas").getBoundingClientRect();
                        setTip({ n, x: ev.clientX - rect.left + 14, y: ev.clientY - rect.top + 10 });
                      }}
                      onClick={(ev) => { ev.stopPropagation(); setSelectedId(n.id); setActiveCluster(null); }}
                      onDoubleClick={(ev) => { ev.stopPropagation(); nav("detail", { id: n.id }); }}
                      opacity={opacity}>
                      {isHalo && (
                        <circle r={r + CLUSTER_HALO_MARGIN} fill="none" stroke={clusterColorById[n.cluster]}
                          strokeWidth={CLUSTER_HALO_WIDTH} strokeOpacity="0.65" filter="url(#gr-glow)" />
                      )}
                      <NodeShape kind={n.kind} r={r}
                        fill={`color-mix(in srgb, ${col} ${st === "superseded" || st === "reverted" ? 16 : 32}%, var(--panel))`}
                        stroke={(isHover || isSelected) ? FOCUS_RING_COLOR : (ring.color || col)}
                        strokeWidth={(isHover || isSelected) ? ring.width + 0.6 : ring.width}
                        strokeDasharray={ring.dash}
                        strokeOpacity={ring.opacity} />
                      {showLabel && (
                        <text y={(r + LABEL_GAP / view.zoom).toFixed(2)} textAnchor="middle" fontSize={(LABEL_FONT_BASE / view.zoom).toFixed(2)} fill={LABEL_TEXT_COLOR} fontWeight="600">{n.label}</text>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>
            {tip && (
              <div className="gr-tip" style={{ left: tip.x, top: tip.y }}>
                <div className="id">{tip.n.id} · {tip.n.kind === "lesson" ? t("ui.graph.tooltip_lesson", "lesson") : t("ui.graph.tooltip_decision", "decision")}</div>
                {tip.n.title}
                <div className="pj">{tip.n.project}</div>
              </div>
            )}
            {!settled && <div className="gr-settle">{t("ui.graph.settling", "Settling layout…")}</div>}
            <div className="gr-stat">
              <span><b>{visibleNodes.length}</b> {t("ui.graph.stat_visible_nodes", "visible nodes")}</span>
              <span><b>{PM.edges.length}</b> {t("ui.graph.stat_edges", "edges")}</span>
              <span><b>{PM.clusters.length}</b> {t("ui.graph.stat_clusters", "clusters")}</span>
              <span><b>{isolatedCount}</b> {t("ui.graph.stat_isolated", "isolated")}</span>
              <span style={{ marginLeft: "auto", color: "var(--faint)" }}>
                {t("ui.graph.canvas_hint", "sample of the {count}-node graph · scroll to zoom, drag to pan · click to select · double-click or the panel button to open record").replace("{count}", PM.stats.graphNodes)}
              </span>
            </div>
          </div>
          )}

          <div className="gr-side">
            <div className="pm-card gr-panel">
              <div className="gr-ph"><Icon name="dot" size={13} /> {t("ui.graph.legend_heading", "Legend")}</div>
              <div className="gr-legend-sub">{t("ui.graph.legend_type_heading", "Type")}</div>
              <div className="gr-keyrow">
                <svg width="14" height="14" viewBox="-8 -8 16 16">
                  <circle r="6" fill={`color-mix(in srgb, ${TYPE_COLOR.decision} 32%, var(--panel))`} stroke={TYPE_COLOR.decision} strokeWidth="1.6" />
                </svg>
                {t("ui.graph.legend_decision", "Decision")}<span className="gr-keydesc">{t("ui.graph.legend_decision_shape", "circle")}</span>
              </div>
              <div className="gr-keyrow">
                <svg width="14" height="14" viewBox="-8 -8 16 16">
                  <polygon points="0,-7 7,0 0,7 -7,0" fill={`color-mix(in srgb, ${TYPE_COLOR.lesson} 32%, var(--panel))`} stroke={TYPE_COLOR.lesson} strokeWidth="1.6" />
                </svg>
                {t("ui.graph.legend_lesson", "Lesson")}<span className="gr-keydesc">{t("ui.graph.legend_lesson_shape", "diamond")}</span>
              </div>
              <div className="gr-legend-sub">{t("ui.graph.legend_status_heading", "Status")}</div>
              {STATUS_ORDER.map((st) => {
                const ring = STATUS_RING[st];
                const info = STATUS_I18N[st];
                return (
                  <div className="gr-keyrow" key={st}>
                    <svg width="14" height="14" viewBox="-8 -8 16 16">
                      <circle r="6" fill="none" stroke={ring.color || LEGEND_RING_NEUTRAL}
                        strokeWidth={ring.width} strokeDasharray={ring.dash} strokeOpacity={ring.opacity} />
                    </svg>
                    {t(...info.label)}<span className="gr-keydesc">{t(...info.style)}</span>
                  </div>
                );
              })}
              <div className="gr-legend-sub">{t("ui.graph.legend_edge_heading", "Edge type")}</div>
              {EDGE_TYPE_ORDER.map((et) => (
                <div className="gr-keyrow" key={et}>
                  <svg width="18" height="10" viewBox="0 0 18 10">
                    <line x1="1" y1="5" x2="17" y2="5" stroke="var(--line2)" strokeWidth="1.8" strokeDasharray={EDGE_DASH[et]} />
                  </svg>
                  {t(...EDGE_TYPE_I18N[et])}
                </div>
              ))}
              <div className="gr-keyrow" style={{ marginTop: 6 }}>
                <svg width="18" height="10" viewBox="0 0 18 10">
                  <line x1="1" y1="5" x2="17" y2="5" stroke={UNEXPECTED_COLOR} strokeWidth="2.4" strokeDasharray="4 3" />
                </svg>
                {t("ui.graph.legend_unexpected", "Unexpected link")}<span className="gr-keydesc">{t("ui.graph.legend_unexpected_style", "glow + flow")}</span>
              </div>
            </div>
            {selectedId ? (
              <div className="pm-card gr-panel">
                <div className="gr-ph"><Icon name="decision" size={13} /> {t("ui.graph.selected_heading", "Selected")}
                  <button className="gr-panelclose" aria-label={t("ui.graph.clear_selection", "Clear selection")} onClick={() => setSelectedId(null)}>
                    <Icon name="close" size={12} />
                  </button>
                </div>
                {(() => {
                  const rec = pmById(selectedId);
                  if (!rec) return <div className="pm-empty" style={{ padding: "14px 0" }}>{t("ui.graph.record_not_found", "Record not found")}</div>;
                  return (
                    <div className="gr-detail">
                      <div className="gr-d-id">{rec.id}</div>
                      <div className="gr-d-title">{rec.title}</div>
                      <div className="gr-d-meta">
                        <span className="pm-tag">{rec.project}</span>
                        <StatusPill status={statuses[rec.id] || rec.status} />
                      </div>
                      <div className="gr-d-row"><span>{t("ui.graph.date", "Date")}</span><b>{rec.date}</b></div>
                      <div className="gr-d-row"><span>{t("ui.graph.importance", "Importance")}</span><Importance value={rec.importance} w={70} /></div>
                      <button className="pm-btn sm accent" style={{ marginTop: 4 }} onClick={() => nav("detail", { id: rec.id })}>
                        <Icon name="arrowRight" size={13} /> {t("ui.graph.go_to_record", "Go to record")}
                      </button>
                      <div className="gr-ph" style={{ marginTop: 12 }}>{t("ui.graph.neighbors", "Neighbors")}<span className="n">{neighborRows.length}</span></div>
                      <div className="gr-neigh">
                        {neighborRows.map((row) => (
                          <button key={row.id} className="gr-neighrow" onClick={() => focusNode(row.id)}>
                            <span className="id">{row.id}</span>
                            <span className="ty">{edgeTypeLabel(row.type)}</span>
                            <span className="cf">%{Math.round(row.conf * 100)}</span>
                          </button>
                        ))}
                        {!neighborRows.length && <div className="pm-empty" style={{ padding: "10px 0" }}>{t("ui.graph.no_neighbors", "No neighbors")}</div>}
                      </div>
                    </div>
                  );
                })()}
              </div>
            ) : (
              <div className="pm-card gr-panel">
                <div className="gr-ph"><Icon name="filter" size={13} /> {t("ui.graph.clusters_heading", "Clusters")}</div>
                <div className="gr-leg">
                  {visibleClusterList.map((c, idx) => {
                    const n = clusterCounts[c.id] || 0;
                    const off = activeCluster && activeCluster !== c.id;
                    const isSmallCluster = idx >= CLUSTER_TOP_COUNT;
                    return (
                      <button key={c.id} className={"gr-legrow" + (off ? " off" : "")} onClick={() => onClusterClick(c.id)} title={c.label}>
                        <span className="sw" style={{ background: clusterSwatchColor(idx, c.color) }} />
                        <span className="gr-leglabel">{c.label}</span>
                        {isSmallCluster && <span className="gr-legsmalltag">{t("ui.graph.legend_small_cluster", "small cluster")}</span>}
                        <span className="n">{n}</span>
                      </button>
                    );
                  })}
                </div>
                {hiddenClusterCount > 0 && (
                  <button className="pm-btn ghost sm" style={{ width: "100%", marginTop: 6 }}
                    onClick={() => setClustersExpanded((v) => !v)}>
                    {clustersExpanded ? t("ui.graph.show_less", "Show less") : `${t("ui.graph.show_more", "More")} (+${hiddenClusterCount})`}
                  </button>
                )}
              </div>
            )}
            <div className="pm-card gr-panel">
              <div className="gr-ph"><Icon name="spark" size={13} style={{ color: "var(--accent-ink)" }} /> {t("ui.graph.unexpected_heading", "Unexpected connections")}</div>
              <div className="gr-unexp">
                {unexpected.map((e, i) => (
                  <div key={i} className="gr-urow" onClick={() => nav("detail", { id: e.from })}
                    onMouseEnter={() => setHover(e.from)} onMouseLeave={() => setHover(null)}>
                    <div className="top">{e.from} <Icon name="link" size={11} /> {e.to}<span className="conf">%{Math.round(e.conf * 100)}</span></div>
                    <div className="dd">{(pmById(e.from) || {}).project || ""} ↔ {(pmById(e.to) || {}).project || ""}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
  function GraphTable({ nodes, neighbors, statuses, nav }) {
    return (
      <div className="gr-tablewrap">
        <table className="gr-table">
          <caption>{t("ui.graph.table_caption", "Accessible list of graph nodes")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("ui.graph.table_col_id", "ID")}</th>
              <th scope="col">{t("ui.graph.table_col_title", "Title")}</th>
              <th scope="col">{t("ui.graph.table_col_type", "Type")}</th>
              <th scope="col">{t("ui.graph.table_col_status", "Status")}</th>
              <th scope="col">{t("ui.graph.table_col_project", "Project")}</th>
              <th scope="col">{t("ui.graph.table_col_degree", "Degree")}</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((n) => {
              const typeKey = n.kind === "lesson" ? "lesson" : "decision";
              const degree = neighbors[n.id] ? neighbors[n.id].size : 0;
              return (
                <tr key={n.id} onClick={() => nav("detail", { id: n.id })} style={{ cursor: "pointer" }}>
                  <td className="id">
                    <button className="gr-idbtn" onClick={(ev) => { ev.stopPropagation(); nav("detail", { id: n.id }); }}>{n.id}</button>
                  </td>
                  <td className="ti" title={n.title}>{n.title}</td>
                  <td><KindTag kind={typeKey} /></td>
                  <td><StatusPill status={statuses[n.id] || n.status} /></td>
                  <td>{n.project}</td>
                  <td>{degree}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!nodes.length && <div className="pm-empty">{t("ui.graph.table_empty", "No nodes match the current filters")}</div>}
      </div>
    );
  }

  window.PMGraph = GraphView;
})();
