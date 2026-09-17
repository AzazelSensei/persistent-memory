// persistent-memory — AI Council board: live multi-agent message stream.
(function () {
  const React = window.React;
  const { useState, useEffect, useRef, useCallback, useMemo } = React;
  const { Icon, renderRefs } = window.PMUI;

  function renderBody(text, nav) {
    const md = window.PMMarkdown;
    if (!md) return { nodes: renderRefs(text, nav), formatted: false };
    return { nodes: md.renderMarkdown(text, { nav }), formatted: true };
  }

  const POLL_INTERVAL_MS = 5000;
  const BOARD_FETCH_LIMIT = 50;
  const MAX_MESSAGES = 500;
  const GENERAL_THREAD = "general";
  const ALL_THREADS = "";
  const REF_ID_RE = /^[DLP]-\d{4}$/;
  const COUNCIL_KINDS = ["note", "proposal", "critique", "vote", "decision", "handoff", "question"];
  const KIND_COLOR = {
    note: "var(--dim)",
    proposal: "var(--accent-ink)",
    critique: "var(--st-reverted)",
    vote: "var(--violet)",
    decision: "var(--st-accepted)",
    handoff: "var(--st-proposed)",
    question: "var(--faint)",
  };
  const ACTIVE_SESSION_STATUSES = ["pending", "running"];
  const TERMINAL_SESSION_STATUSES = ["converged", "failed", "cancelled"];
  const MISSING_TURN_STATUS = "—";
  const SESSION_STATUS_COLOR = {
    pending: "var(--faint)",
    running: "var(--violet)",
    converged: "var(--st-accepted)",
    failed: "var(--st-reverted)",
    cancelled: "var(--dim)",
  };
  const TURN_STATUS_COLOR = {
    pending: "var(--faint)",
    running: "var(--violet)",
    done: "var(--st-accepted)",
    failed: "var(--st-reverted)",
    timeout: "var(--st-proposed)",
    skipped: "var(--dim)",
  };
  const SESSION_LIST_LIMIT = 50;
  const FORM_MIN_ROUNDS = 1;
  const FORM_MAX_ROUNDS = 5;
  const SESSION_TOPIC_PREVIEW_CHARS = 140;
  const ALL_SESSIONS_LIMIT = 200;
  const SESSION_SCOPE_ALL = "all";
  const SESSION_SCOPE_PROJECT = "project";
  const STREAM_STATUS_LIVE = "live";
  const STREAM_STATUS_RECONNECTING = "reconnecting";
  const STREAM_STATUS_POLLING = "polling";
  const THREADS_REFRESH_DEBOUNCE_MS = 800;

  if (!document.getElementById("pm-council-css")) {
    const s = document.createElement("style");
    s.id = "pm-council-css";
    s.textContent = `
.l-sel{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);color:var(--txt);font-family:inherit;font-size:12.5px;padding:7px 9px;cursor:pointer}
.cn-headrow{display:flex;align-items:center;gap:16px}
.cn-live{margin-left:auto;display:flex;align-items:center;gap:10px}
.cn-livebtn{display:flex;align-items:center;gap:7px;border:1px solid var(--line);background:var(--panel);color:var(--dim);border-radius:999px;padding:6px 12px;font-size:12px;font-family:inherit;cursor:pointer}
.cn-livebtn .dot{width:7px;height:7px;border-radius:50%;background:var(--faint)}
.cn-livebtn.on{color:var(--st-accepted);border-color:color-mix(in srgb,var(--st-accepted) 40%,var(--line2))}
.cn-livebtn.on .dot{background:var(--st-accepted);box-shadow:var(--glow) var(--st-accepted)}
.cn-livebtn.err{color:var(--st-reverted);border-color:color-mix(in srgb,var(--st-reverted) 40%,var(--line2))}
.cn-livebtn.err .dot{background:var(--st-reverted)}
.cn-updated{font-family:var(--font-mono);font-size:11px;color:var(--faint)}
.cn-toolbar{display:flex;gap:14px;margin-top:18px;flex-wrap:wrap}
.cn-field{display:flex;flex-direction:column;gap:5px}
.cn-field .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--faint)}
.cn-field select{min-width:180px}
.cn-stream{display:flex;flex-direction:column;gap:11px;margin-top:20px}
.cn-card{padding:13px 16px}
.cn-top{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.cn-author{font-size:12.5px;font-weight:600;color:var(--txt-hi)}
.cn-via{font-family:var(--font-mono);font-size:10px;text-transform:uppercase;letter-spacing:.3px;color:var(--dim);border:1px solid var(--line);border-radius:999px;padding:1px 7px}
.cn-kind{font-family:var(--font-mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;padding:2px 8px;border-radius:999px;background:var(--panel-hi);border:1px solid var(--line)}
.cn-turn{font-family:var(--font-mono);font-size:10.5px;color:var(--dim);background:var(--panel-hi);border:1px solid var(--line);border-radius:999px;padding:2px 8px}
.cn-fallback{font-family:var(--font-mono);font-size:10px;color:var(--st-proposed);border:1px solid color-mix(in srgb,var(--st-proposed) 40%,var(--line2));border-radius:999px;padding:2px 7px}
.cn-sp{flex:1}
.cn-time{font-family:var(--font-mono);font-size:11.5px;color:var(--faint)}
.cn-id{font-family:var(--font-mono);font-size:11px;color:var(--faint)}
.cn-body{margin-top:10px;font-size:13px;color:var(--txt);white-space:pre-wrap;line-height:1.55}
.cn-body.md{white-space:normal}
.cn-body.md>:first-child{margin-top:0}
.cn-body.md>:last-child{margin-bottom:0}
.cn-refs{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
.cn-refbadge{font-family:var(--font-mono);font-size:11px;color:var(--accent-ink);border:1px solid var(--accent-line);border-radius:999px;padding:2px 9px}
.cn-compose{margin-top:22px;padding:16px 17px}
.cn-textarea{width:100%;min-height:78px;background:var(--bg2);color:var(--txt-hi);border:1px solid var(--line2);border-radius:var(--r-sm);padding:11px 12px;font-family:inherit;font-size:13px;line-height:1.5;resize:vertical;outline:none}
.cn-composebar{display:flex;align-items:center;gap:9px;margin-top:11px}
.cn-threadinput{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);color:var(--txt);font-family:inherit;font-size:12.5px;padding:7px 9px;width:160px}
.cn-err{margin-top:9px;font-size:12.5px;color:var(--st-reverted)}
.cn-err-hint{margin-top:6px;font-size:11.5px;color:var(--faint)}
.cn-tabs{display:flex;gap:6px;margin-top:20px;border-bottom:1px solid var(--line)}
.cn-tab{background:none;border:none;border-bottom:2px solid transparent;color:var(--dim);font-family:inherit;font-size:12.5px;padding:9px 4px;margin-bottom:-1px;cursor:pointer}
.cn-tab.on{color:var(--txt-hi);border-bottom-color:var(--accent-ink)}
.cn-sess-form{margin-top:18px;padding:14px 16px}
.cn-formtoggle{display:flex;align-items:center;gap:7px;background:none;border:none;color:var(--txt-hi);font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;padding:0}
.cn-formbody{display:flex;flex-direction:column;gap:12px;margin-top:14px}
.cn-forminput{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-sm);color:var(--txt);font-family:inherit;font-size:12.5px;padding:7px 9px}
.cn-checkrow{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--txt)}
.cn-preview{margin-top:10px;padding-top:10px;border-top:1px solid var(--line)}
.cn-preview-head{font-size:12.5px;font-weight:600;color:var(--txt-hi)}
.cn-preview-block{margin-top:8px;border:1px solid var(--line);border-radius:var(--r-sm);padding:8px 10px}
.cn-preview-block summary{cursor:pointer;font-family:var(--font-mono);font-size:11.5px;color:var(--dim)}
.cn-preview-pre{white-space:pre-wrap;font-family:var(--font-mono);font-size:11.5px;color:var(--txt);margin:8px 0 0;max-height:260px;overflow:auto}
.cn-sess-layout{display:grid;grid-template-columns:minmax(220px,320px) 1fr;gap:16px;margin-top:18px;align-items:start}
.cn-sess-list{display:flex;flex-direction:column;gap:9px}
.cn-sess-row{padding:11px 13px;cursor:pointer}
.cn-sess-row.sel{border-color:var(--accent-ink)}
.cn-sess-top{display:flex;align-items:center;gap:8px}
.cn-sess-id{font-family:var(--font-mono);font-size:11.5px;color:var(--faint)}
.cn-sess-topic{margin-top:6px;font-size:12.5px;color:var(--txt)}
.cn-sess-meta{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;font-family:var(--font-mono);font-size:10.5px;color:var(--faint)}
.cn-sess-record{color:var(--accent-ink);cursor:pointer}
.cn-sess-badge{font-family:var(--font-mono);font-size:10px;text-transform:uppercase;letter-spacing:.3px;border:1px solid var(--line2);border-radius:999px;padding:1px 8px}
.cn-sess-detail{padding:16px 18px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r)}
.cn-detail-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.cn-detail-topic{margin-top:10px;font-size:13px;color:var(--txt);white-space:pre-wrap;line-height:1.5}
.cn-confirm{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--txt)}
.cn-matrix-head{margin-top:18px;font-size:12px;font-weight:600;color:var(--txt-hi);text-transform:uppercase;letter-spacing:.4px}
.cn-matrix-wrap{margin-top:10px;overflow-x:auto}
.cn-matrix{border-collapse:collapse;width:100%;font-size:11.5px}
.cn-matrix th,.cn-matrix td{border:1px solid var(--line);padding:6px 10px;text-align:left;white-space:nowrap}
.cn-matrix th{color:var(--faint);font-family:var(--font-mono);font-weight:500}
.cn-matrix-label{font-family:var(--font-mono);color:var(--dim)}
.cm-cell{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-mono);text-transform:uppercase;font-size:10.5px}
.cm-via{color:var(--faint);border:1px solid var(--line);border-radius:999px;padding:0 6px;text-transform:none}
.cn-muted{color:var(--faint)}
.cn-scopetoggle{display:flex;gap:6px}
.cn-scopebtn{background:var(--panel);border:1px solid var(--line);border-radius:999px;color:var(--dim);font-family:inherit;font-size:11.5px;padding:5px 11px;cursor:pointer}
.cn-scopebtn.on{color:var(--txt-hi);border-color:var(--accent-ink);background:var(--panel-hi)}
.cn-projbadge{font-family:var(--font-mono);font-size:10px;text-transform:uppercase;letter-spacing:.3px;color:var(--dim);border:1px solid var(--line);border-radius:999px;padding:1px 7px}
.cn-live-badge{display:inline-flex;align-items:center;gap:5px;font-family:var(--font-mono);font-size:10px;text-transform:uppercase;letter-spacing:.3px;color:var(--st-accepted);border:1px solid color-mix(in srgb,var(--st-accepted) 40%,var(--line2));border-radius:999px;padding:1px 8px}
.cn-live-badge .dot{width:6px;height:6px;border-radius:50%;background:var(--st-accepted);box-shadow:var(--glow) var(--st-accepted)}
.cn-connstate{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-mono);font-size:11px;text-transform:uppercase;letter-spacing:.3px}
.cn-connstate .dot{width:7px;height:7px;border-radius:50%}
.cn-connstate.live{color:var(--st-accepted)}
.cn-connstate.live .dot{background:var(--st-accepted);box-shadow:var(--glow) var(--st-accepted)}
.cn-connstate.reconnecting{color:var(--st-proposed)}
.cn-connstate.reconnecting .dot{background:var(--st-proposed)}
.cn-connstate.polling{color:var(--faint)}
.cn-connstate.polling .dot{background:var(--faint)}
.cn-sel-badge{display:inline-flex;align-items:center;gap:5px;font-family:var(--font-mono);font-size:11px;color:var(--faint);border:1px solid var(--line);border-radius:999px;padding:2px 9px}
.cn-sel-badge.active{color:var(--st-accepted);border-color:color-mix(in srgb,var(--st-accepted) 40%,var(--line2))}
.cn-sel-badge .dot{width:6px;height:6px;border-radius:50%;background:var(--st-accepted)}
`;
    document.head.appendChild(s);
  }

  function fmtTime(ts) {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return "";
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return hh + ":" + mm;
  }

  function fmtStamp(ts) {
    if (!ts) return "";
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return "";
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const da = String(d.getDate()).padStart(2, "0");
    return mo + "/" + da + " " + fmtTime(ts);
  }

  function messageSeq(id) {
    if (!id) return -1;
    const n = parseInt(String(id).split("-")[1], 10);
    return Number.isNaN(n) ? -1 : n;
  }

  function mergeMessages(prev, fresh) {
    if (fresh.length === 0) return prev;
    const seen = new Set(prev.map((m) => m.id));
    const merged = prev.slice();
    for (const m of fresh) {
      if (seen.has(m.id)) continue;
      seen.add(m.id);
      merged.push(m);
    }
    return merged.slice(-MAX_MESSAGES);
  }

  function fetchAllCouncilSessions(limit) {
    const params = new URLSearchParams();
    if (limit) params.set("limit", String(limit));
    return fetch("/api/council/sessions/all?" + params.toString())
      .then((r) => r.json().catch(() => ({})).then((body) => ({ ok: r.ok, status: r.status, sessions: body.sessions || [] })))
      .catch(() => ({ ok: false, status: 0, sessions: [] }));
  }

  function councilStreamUrl(project, sessionId) {
    const params = new URLSearchParams({ project });
    if (sessionId) params.set("session", sessionId);
    return "/api/council/stream?" + params.toString();
  }

  function sortSessionsActiveFirst(sessions) {
    return sessions
      .map((session, index) => ({ session, index }))
      .sort((a, b) => {
        const aActive = ACTIVE_SESSION_STATUSES.indexOf(a.session.status) >= 0 ? 0 : 1;
        const bActive = ACTIVE_SESSION_STATUSES.indexOf(b.session.status) >= 0 ? 0 : 1;
        if (aActive !== bActive) return aActive - bActive;
        return a.index - b.index;
      })
      .map((entry) => entry.session);
  }

  function useCouncilStream({ enabled, url, onMessage, onSession }) {
    const [status, setStatus] = useState(STREAM_STATUS_LIVE);
    const onMessageRef = useRef(onMessage);
    const onSessionRef = useRef(onSession);
    useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);
    useEffect(() => { onSessionRef.current = onSession; }, [onSession]);

    useEffect(() => {
      if (!enabled || !url || typeof window.EventSource === "undefined") {
        setStatus(STREAM_STATUS_POLLING);
        return undefined;
      }

      let cancelled = false;
      let es = null;
      const retriedRef = { current: false };

      function connect() {
        es = new EventSource(url);
        es.onopen = () => {
          if (cancelled) return;
          retriedRef.current = false;
          setStatus(STREAM_STATUS_LIVE);
        };
        es.addEventListener("message", (event) => {
          if (cancelled) return;
          setStatus(STREAM_STATUS_LIVE);
          try {
            onMessageRef.current && onMessageRef.current(JSON.parse(event.data));
          } catch (err) {
            console.warn("council stream: malformed message event", err);
          }
        });
        es.addEventListener("session", (event) => {
          if (cancelled) return;
          setStatus(STREAM_STATUS_LIVE);
          try {
            onSessionRef.current && onSessionRef.current(JSON.parse(event.data));
          } catch (err) {
            console.warn("council stream: malformed session event", err);
          }
        });
        es.addEventListener("ping", () => {});
        es.onerror = () => {
          if (cancelled) return;
          es.close();
          if (!retriedRef.current) {
            retriedRef.current = true;
            setStatus(STREAM_STATUS_RECONNECTING);
            connect();
            return;
          }
          setStatus(STREAM_STATUS_POLLING);
        };
      }

      setStatus(STREAM_STATUS_LIVE);
      connect();

      return () => {
        cancelled = true;
        if (es) es.close();
      };
    }, [enabled, url]);

    return status;
  }

  function ConnectionIndicator({ status }) {
    if (status === STREAM_STATUS_LIVE) {
      return <span className="cn-connstate live"><span className="dot" />{t("ui.council.live_connected", "stream")}</span>;
    }
    if (status === STREAM_STATUS_RECONNECTING) {
      return <span className="cn-connstate reconnecting"><span className="dot" />{t("ui.council.live_reconnecting", "Reconnecting…")}</span>;
    }
    return <span className="cn-connstate polling"><span className="dot" />{t("ui.council.live_polling", "Polling")}</span>;
  }

  function CouncilProjectBadge({ project }) {
    const [state, setState] = useState(null);

    useEffect(() => {
      if (!project) { setState(null); return undefined; }
      let active = true;
      const load = () => {
        window.PM_API.fetchCouncilSessions(project, SESSION_LIST_LIMIT).then((data) => {
          if (!active || !data.ok) return;
          const list = data.sessions || [];
          setState({
            count: list.length,
            hasActive: list.some((s) => ACTIVE_SESSION_STATUSES.indexOf(s.status) >= 0),
          });
        });
      };
      load();
      const timer = setInterval(() => { if (!document.hidden) load(); }, POLL_INTERVAL_MS);
      return () => { active = false; clearInterval(timer); };
    }, [project]);

    if (!state || state.count === 0) return null;
    return (
      <span className={"cn-sel-badge" + (state.hasActive ? " active" : "")} title={t("ui.council.project_badge", "council sessions in this project")}>
        {state.hasActive && <span className="dot" />}
        {state.count}
      </span>
    );
  }

  function RefBadge({ id, nav }) {
    const registry = (window.PM && window.PM.byId) || {};
    const validId = REF_ID_RE.test(id);
    const known = validId && Object.prototype.hasOwnProperty.call(registry, id) ? registry[id] : null;
    return (
      <span className="cn-refbadge" title={known ? known.title : id}
        style={{ cursor: known ? "pointer" : "default" }}
        onClick={() => known && nav && nav("detail", { id })}>{id}</span>
    );
  }

  const MessageCard = React.memo(function MessageCard({ msg, nav }) {
    const body = useMemo(() => renderBody(msg.body, nav), [msg.body, nav]);
    return (
      <div className="pm-card cn-card">
        <div className="cn-top">
          <span className="cn-author">{msg.author}{msg.role ? " · " + msg.role : ""}</span>
          <span className="cn-via">{msg.via || "?"}</span>
          <span className="cn-kind" style={{ color: KIND_COLOR[msg.kind] || "var(--dim)" }}>{msg.kind}</span>
          {msg.turn != null && <span className="cn-turn">{t("ui.council.turn", "turn")} {msg.turn}</span>}
          {msg.via === "stdout" && <span className="cn-fallback" title={t("ui.council.fallback_hint", "captured from stdout fallback")}>{t("ui.council.fallback", "fallback")}</span>}
          <span className="cn-sp" />
          <span className="cn-time">{fmtTime(msg.ts)}</span>
          <span className="cn-id">{msg.id}</span>
        </div>
        <div className={body.formatted ? "cn-body md" : "cn-body"}>{body.nodes}</div>
        {msg.refs && msg.refs.length > 0 && (
          <div className="cn-refs">{msg.refs.map((r, i) => <RefBadge key={r + "-" + i} id={r} nav={nav} />)}</div>
        )}
      </div>
    );
  });

  function SessionStatusBadge({ status }) {
    const color = SESSION_STATUS_COLOR[status] || "var(--dim)";
    return (
      <span className="cn-sess-badge" style={{ color, borderColor: "color-mix(in srgb, " + color + " 45%, var(--line2))" }}>
        {status}
      </span>
    );
  }

  function TurnCell({ turn }) {
    const color = TURN_STATUS_COLOR[turn.status] || "var(--dim)";
    return (
      <span className="cm-cell" style={{ color }} title={turn.error || ""}>
        {turn.status}
        {turn.via && <span className="cm-via">{turn.via}</span>}
      </span>
    );
  }

  function buildTurnMatrix(session) {
    const terminal = TERMINAL_SESSION_STATUSES.indexOf(session.status) >= 0;
    const skippedMembers = new Set(
      session.turns.filter((tn) => tn.round === 1 && tn.status === "skipped").map((tn) => tn.member_id)
    );
    const rounds = [];
    for (let r = 1; r <= session.rounds; r++) {
      const cells = session.members.map((memberId) => {
        const turn = session.turns.find((tn) => tn.round === r && tn.member_id === memberId);
        if (turn) return turn;
        if (skippedMembers.has(memberId)) {
          const skipTurn = session.turns.find(
            (tn) => tn.round === 1 && tn.member_id === memberId && tn.status === "skipped"
          );
          return { round: r, member_id: memberId, status: "skipped", via: null, error: skipTurn ? skipTurn.error : null };
        }
        const status = terminal ? MISSING_TURN_STATUS : "pending";
        return { round: r, member_id: memberId, status, via: null, error: null };
      });
      rounds.push({ round: r, cells });
    }
    // Synthesis lives one round past the last regular round, but session.rounds
    // can be stale (e.g. an early cancel) — use the highest round actually
    // present in turns instead of assuming it is exactly rounds + 1.
    const maxRound = session.turns.reduce((acc, tn) => Math.max(acc, tn.round), session.rounds);
    const synthesisTurns = session.turns.filter((tn) => tn.round === maxRound && tn.round > session.rounds);
    // A failed spokesperson attempt and a successful fallback attempt can
    // both land on the same synthesis round (different member_id) — prefer
    // the one that actually succeeded over whichever was persisted first.
    const synthesis = synthesisTurns.find((tn) => tn.status === "done") || synthesisTurns[synthesisTurns.length - 1] || null;
    return { rounds, synthesis };
  }

  function SessionDetail({ session, cancelConfirm, cancelling, cancelErr, onCancelClick, onCancelNo, onCancelYes, threadMessages, streamStatus, nav }) {
    const active = ACTIVE_SESSION_STATUSES.indexOf(session.status) >= 0;
    const matrix = buildTurnMatrix(session);
    return (
      <div>
        <div className="cn-detail-head">
          <span className="cn-sess-id">{session.id}</span>
          <SessionStatusBadge status={session.status} />
          {active && <ConnectionIndicator status={streamStatus} />}
          {active && !cancelConfirm && (
            <button className="pm-btn no sm" onClick={onCancelClick}>{t("ui.council.cancel", "Cancel")}</button>
          )}
          {active && cancelConfirm && (
            <span className="cn-confirm">
              {t("ui.council.cancel_confirm", "Cancel this session?")}
              <button className="pm-btn ok sm" disabled={cancelling} onClick={onCancelYes}>{t("ui.council.yes", "Yes")}</button>
              <button className="pm-btn ghost sm" disabled={cancelling} onClick={onCancelNo}>{t("ui.council.no", "No")}</button>
            </span>
          )}
        </div>
        {cancelErr && <div className="cn-err">{cancelErr}</div>}
        <div className="cn-detail-topic">{session.topic}</div>
        <div className="cn-sess-meta">
          <span>{session.members.length} {t("ui.council.members", "members")}</span>
          <span>{session.rounds} {t("ui.council.rounds_count", "rounds")}</span>
          <span>{t("ui.council.created_at", "created")} {fmtStamp(session.created_at)}</span>
          {session.record_id && (
            <span className="cn-sess-record" onClick={() => nav && nav("detail", { id: session.record_id })}>
              {t("ui.council.record_link", "record")}: {session.record_id}
            </span>
          )}
        </div>

        {window.PMCouncilScene && (
          <window.PMCouncilScene session={session} matrix={matrix} threadMessages={threadMessages} />
        )}

        <div className="cn-matrix-head">{t("ui.council.turn_matrix", "Turn matrix")}</div>
        <div className="cn-matrix-wrap">
          <table className="cn-matrix">
            <thead>
              <tr>
                <th></th>
                {session.members.map((m) => <th key={m}>{m}</th>)}
              </tr>
            </thead>
            <tbody>
              {matrix.rounds.map((row) => (
                <tr key={"r" + row.round}>
                  <td className="cn-matrix-label">{t("ui.council.round_row_prefix", "Round")} {row.round}</td>
                  {row.cells.map((cell) => <td key={cell.member_id}><TurnCell turn={cell} /></td>)}
                </tr>
              ))}
              <tr>
                <td className="cn-matrix-label">{t("ui.council.synthesis_row", "Synthesis")}</td>
                <td colSpan={session.members.length}>
                  {matrix.synthesis ? (
                    <span className="cm-cell">{matrix.synthesis.member_id} <TurnCell turn={matrix.synthesis} /></span>
                  ) : (
                    <span className="cn-muted">{t("ui.council.no_synthesis_yet", "Not reached yet")}</span>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="cn-matrix-head">{t("ui.council.session_thread_heading", "Session activity")}</div>
        <div className="cn-stream">
          {threadMessages.length === 0 && <div className="pm-empty">{t("ui.council.empty", "No messages in this project yet")}</div>}
          {threadMessages.map((m) => <MessageCard key={m.id} msg={m} nav={nav} />)}
        </div>
      </div>
    );
  }

  function SessionsPanel({ project, onSelectProject, nav }) {
    const [scope, setScope] = useState(SESSION_SCOPE_ALL);
    const [sessions, setSessions] = useState([]);
    const [sessionsLoading, setSessionsLoading] = useState(true);
    const [sessionsError, setSessionsError] = useState(false);
    const [selectedId, setSelectedId] = useState(null);
    const [selectedProject, setSelectedProject] = useState(null);
    const [selectedSession, setSelectedSession] = useState(null);
    const [selectedError, setSelectedError] = useState(false);
    const [threadMessages, setThreadMessages] = useState([]);
    const [cancelConfirm, setCancelConfirm] = useState(false);
    const [cancelling, setCancelling] = useState(false);
    const [cancelErr, setCancelErr] = useState("");
    const [formOpen, setFormOpen] = useState(false);
    const [formTopic, setFormTopic] = useState("");
    const [formCwd, setFormCwd] = useState("");
    const [formRounds, setFormRounds] = useState("");
    const [formDryRun, setFormDryRun] = useState(false);
    const [formSubmitting, setFormSubmitting] = useState(false);
    const [formErr, setFormErr] = useState("");
    const [dryRunPreview, setDryRunPreview] = useState(null);

    const listInFlightRef = useRef(false);
    const listPendingRef = useRef(false);
    const sessionInFlightRef = useRef(false);
    const boardInFlightRef = useRef(false);
    const threadCursorRef = useRef(null);
    const selectedIdRef = useRef(null);
    const projectRef = useRef(project);
    const scopeRef = useRef(scope);

    useEffect(() => { projectRef.current = project; }, [project]);
    useEffect(() => { scopeRef.current = scope; }, [scope]);
    useEffect(() => { selectedIdRef.current = selectedId; }, [selectedId]);

    // Stable identity (no `project`/`scope` dependency): always reads the
    // latest values via refs so a request queued while an older project's
    // fetch is in flight resolves against whichever project/scope is current
    // by the time it actually runs, instead of being silently dropped.
    const refreshSessions = useCallback((selectAfter) => {
      const currentScope = scopeRef.current;
      const currentProject = projectRef.current;
      if (currentScope === SESSION_SCOPE_PROJECT && !currentProject) {
        setSessions([]);
        setSessionsLoading(false);
        return;
      }
      if (listInFlightRef.current) { listPendingRef.current = true; return; }
      listInFlightRef.current = true;
      const request = currentScope === SESSION_SCOPE_ALL
        ? fetchAllCouncilSessions(ALL_SESSIONS_LIMIT)
        : window.PM_API.fetchCouncilSessions(currentProject, SESSION_LIST_LIMIT);
      request.then((data) => {
        if (currentScope !== scopeRef.current) return;
        if (currentScope === SESSION_SCOPE_PROJECT && currentProject !== projectRef.current) return;
        if (!data.ok) { setSessionsError(true); setSessionsLoading(false); return; }
        setSessionsError(false);
        setSessions(sortSessionsActiveFirst(data.sessions || []));
        setSessionsLoading(false);
        if (selectAfter) {
          setSelectedId(selectAfter.id);
          setSelectedProject(selectAfter.project);
        }
      }).finally(() => {
        listInFlightRef.current = false;
        if (listPendingRef.current) {
          listPendingRef.current = false;
          refreshSessions();
        }
      });
    }, []);

    useEffect(() => {
      setSessions([]);
      setSessionsLoading(true);
      setSessionsError(false);
      if (scope === SESSION_SCOPE_PROJECT) {
        setSelectedId(null);
        setSelectedProject(null);
      }
      refreshSessions();
    }, [scope, project, refreshSessions]);

    const hasActiveSession = sessions.some((s) => ACTIVE_SESSION_STATUSES.indexOf(s.status) >= 0);

    useEffect(() => {
      if (scope === SESSION_SCOPE_PROJECT && !project) return undefined;
      if (!hasActiveSession) return undefined;
      const timer = setInterval(() => {
        if (document.hidden) return;
        refreshSessions();
      }, POLL_INTERVAL_MS);
      return () => clearInterval(timer);
    }, [scope, project, hasActiveSession, refreshSessions]);

    const onSelectSession = (s) => {
      setSelectedId(s.id);
      setSelectedProject(s.project);
      if (s.project !== project) onSelectProject(s.project);
    };

    useEffect(() => {
      setCancelConfirm(false);
      setCancelErr("");
      if (!selectedId || !selectedProject) {
        setSelectedSession(null);
        setThreadMessages([]);
        setSelectedError(false);
        return undefined;
      }
      let active = true;
      const reqId = selectedId;
      const reqProject = selectedProject;
      threadCursorRef.current = null;
      setThreadMessages([]);
      setSelectedSession(null);
      setSelectedError(false);

      window.PM_API.fetchCouncilSession(reqProject, reqId).then((data) => {
        if (!active) return;
        if (!data.ok) { setSelectedError(true); return; }
        setSelectedError(false);
        setSelectedSession(data.session);
      });
      window.PM_API.fetchCouncilBoard(reqProject, reqId, null, BOARD_FETCH_LIMIT).then((data) => {
        if (!active || !data.ok) return;
        const fresh = data.messages || [];
        setThreadMessages(fresh.slice(-MAX_MESSAGES));
        threadCursorRef.current = fresh.length > 0 ? fresh[fresh.length - 1].id : null;
      });
      return () => { active = false; };
    }, [selectedProject, selectedId]);

    const selectedStatus = selectedSession && selectedSession.status;
    const selectedActive = !!selectedStatus && ACTIVE_SESSION_STATUSES.indexOf(selectedStatus) >= 0;

    const onStreamMessage = useCallback((msg) => {
      if (msg.thread !== selectedIdRef.current) return;
      setThreadMessages((prev) => mergeMessages(prev, [msg]));
      if (messageSeq(msg.id) > messageSeq(threadCursorRef.current)) {
        threadCursorRef.current = msg.id;
      }
    }, []);

    const onStreamSession = useCallback((sessionData) => {
      if (sessionData.id !== selectedIdRef.current) return;
      setSelectedError(false);
      setSelectedSession(sessionData);
    }, []);

    const sessionStreamUrl = selectedActive && selectedProject && selectedId
      ? councilStreamUrl(selectedProject, selectedId)
      : null;

    const sessionStreamStatus = useCouncilStream({
      enabled: !!sessionStreamUrl,
      url: sessionStreamUrl,
      onMessage: onStreamMessage,
      onSession: onStreamSession,
    });

    useEffect(() => {
      if (!selectedActive || !selectedId || !selectedProject) return undefined;
      if (sessionStreamStatus !== STREAM_STATUS_POLLING) return undefined;
      let active = true;
      const reqId = selectedId;
      const reqProject = selectedProject;
      const timer = setInterval(() => {
        if (document.hidden) return;
        if (!sessionInFlightRef.current) {
          sessionInFlightRef.current = true;
          window.PM_API.fetchCouncilSession(reqProject, reqId).then((data) => {
            if (!active) return;
            if (!data.ok) { setSelectedError(true); return; }
            setSelectedError(false);
            setSelectedSession(data.session);
          }).finally(() => { sessionInFlightRef.current = false; });
        }
        if (!boardInFlightRef.current) {
          boardInFlightRef.current = true;
          const cursorAtRequest = threadCursorRef.current;
          window.PM_API.fetchCouncilBoard(reqProject, reqId, cursorAtRequest, BOARD_FETCH_LIMIT).then((data) => {
            if (!active || !data.ok) return;
            const fresh = data.messages || [];
            if (fresh.length === 0) return;
            setThreadMessages((prev) => mergeMessages(prev, fresh));
            const lastId = fresh[fresh.length - 1].id;
            if (messageSeq(lastId) > messageSeq(threadCursorRef.current)) {
              threadCursorRef.current = lastId;
            }
          }).finally(() => { boardInFlightRef.current = false; });
        }
      }, POLL_INTERVAL_MS);
      return () => { active = false; clearInterval(timer); };
    }, [selectedActive, selectedId, selectedProject, sessionStreamStatus]);

    const onSubmitForm = () => {
      if (!project || formSubmitting) return;
      if (!formTopic.trim() || !formCwd.trim()) return;
      setFormSubmitting(true);
      setFormErr("");
      setDryRunPreview(null);
      const payload = { project, cwd: formCwd.trim(), topic: formTopic.trim(), dry_run: formDryRun };
      const roundsNum = formRounds ? parseInt(formRounds, 10) : 0;
      if (roundsNum >= FORM_MIN_ROUNDS) payload.rounds = roundsNum;
      window.PM_API.postCouncilSession(payload).then((res) => {
        setFormSubmitting(false);
        if (!res.ok) {
          const detail = res.detail ? " — " + res.detail : "";
          setFormErr(t("ui.council.session_error", "Couldn't start session") + " (HTTP " + res.status + ")" + detail);
          return;
        }
        if (formDryRun) {
          setDryRunPreview(res.body);
          return;
        }
        setFormTopic("");
        setFormCwd("");
        setFormRounds("");
        setFormOpen(false);
        refreshSessions({ id: res.body.id, project });
      });
    };

    const onCancelYes = () => {
      if (!selectedId || !selectedProject || cancelling) return;
      const reqId = selectedId;
      const reqProject = selectedProject;
      setCancelling(true);
      setCancelErr("");
      window.PM_API.cancelCouncilSession(reqProject, reqId).then((res) => {
        setCancelling(false);
        setCancelConfirm(false);
        if (!res.ok) {
          const detail = res.detail ? " — " + res.detail : "";
          setCancelErr(t("ui.council.cancel_failed", "Cancel failed") + " (HTTP " + res.status + ")" + detail);
          return;
        }
        window.PM_API.fetchCouncilSession(reqProject, reqId).then((data) => {
          // The user may have selected a different session while this
          // request was in flight — only apply it if it still matches.
          if (data.ok && selectedIdRef.current === reqId) setSelectedSession(data.session);
        });
        refreshSessions();
      });
    };

    return (
      <div>
        <div className="pm-card cn-sess-form">
          <button className="cn-formtoggle" onClick={() => setFormOpen((v) => !v)}>
            <Icon name="chevR" size={13} style={{ transform: formOpen ? "rotate(90deg)" : "none" }} />
            {t("ui.council.new_session", "New session")}
          </button>
          {formOpen && (
            <div className="cn-formbody">
              <label className="cn-field">
                <span className="l">{t("ui.council.topic", "Topic")}</span>
                <textarea className="cn-textarea" value={formTopic} onChange={(e) => setFormTopic(e.target.value)}
                  placeholder={t("ui.council.topic_placeholder", "What should the council decide?")} spellCheck={false} required />
              </label>
              <label className="cn-field">
                <span className="l">{t("ui.council.cwd", "Working directory")}</span>
                <input className="cn-forminput" value={formCwd} onChange={(e) => setFormCwd(e.target.value)}
                  placeholder={t("ui.council.cwd_placeholder", "/absolute/path/to/project")} required />
              </label>
              <label className="cn-field">
                <span className="l">{t("ui.council.rounds", "Rounds")}</span>
                <input className="cn-forminput" type="number" min={FORM_MIN_ROUNDS} max={FORM_MAX_ROUNDS}
                  value={formRounds} onChange={(e) => setFormRounds(e.target.value)} style={{ width: 90 }} />
              </label>
              <label className="cn-checkrow">
                <input type="checkbox" checked={formDryRun} onChange={(e) => setFormDryRun(e.target.checked)} />
                {t("ui.council.dry_run", "Preview only (dry-run)")}
              </label>
              <div>
                <button className="pm-btn accent" disabled={!formTopic.trim() || !formCwd.trim() || formSubmitting}
                  onClick={onSubmitForm}>
                  {formDryRun ? t("ui.council.preview_btn", "Preview") : t("ui.council.start_session", "Start session")}
                </button>
              </div>
              {formErr && <div className="cn-err">{formErr}</div>}
              {dryRunPreview && (
                <div className="cn-preview">
                  <div className="cn-preview-head">{t("ui.council.preview_heading", "Prompt preview")}</div>
                  <div className="cn-err-hint">{t("ui.council.dry_run_notice", "Preview only — no session was started.")}</div>
                  {Object.keys(dryRunPreview.prompts || {}).map((memberId) => (
                    <details key={memberId} className="cn-preview-block">
                      <summary>{memberId}</summary>
                      <pre className="cn-preview-pre">{dryRunPreview.prompts[memberId]}</pre>
                    </details>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="cn-scopetoggle">
          <button className={"cn-scopebtn" + (scope === SESSION_SCOPE_ALL ? " on" : "")} onClick={() => setScope(SESSION_SCOPE_ALL)}>
            {t("ui.council.all_projects", "All projects")}
          </button>
          <button className={"cn-scopebtn" + (scope === SESSION_SCOPE_PROJECT ? " on" : "")} onClick={() => setScope(SESSION_SCOPE_PROJECT)}>
            {t("ui.council.this_project_only", "This project only")}
          </button>
        </div>

        <div className="cn-sess-layout">
          <div className="cn-sess-list">
            {sessionsLoading && <div className="pm-empty">{t("ui.cand.loading", "Loading…")}</div>}
            {!sessionsLoading && sessionsError && <div className="pm-empty">{t("ui.council.error", "Couldn't reach the council board")}</div>}
            {!sessionsLoading && !sessionsError && sessions.length === 0 && (
              <div className="pm-empty">
                {scope === SESSION_SCOPE_ALL
                  ? t("ui.council.sessions_all_empty", "No council sessions in any project yet")
                  : t("ui.council.sessions_empty", "No sessions yet")}
              </div>
            )}
            {sessions.map((s) => (
              <div key={s.project + "-" + s.id}
                className={"pm-card cn-sess-row" + (s.id === selectedId && s.project === selectedProject ? " sel" : "")}
                onClick={() => onSelectSession(s)}>
                <div className="cn-sess-top">
                  <span className="cn-sess-id">{s.id}</span>
                  <SessionStatusBadge status={s.status} />
                  {scope === SESSION_SCOPE_ALL && <span className="cn-projbadge">{s.project}</span>}
                  {ACTIVE_SESSION_STATUSES.indexOf(s.status) >= 0 && (
                    <span className="cn-live-badge"><span className="dot" />{t("ui.council.running_now", "running now")}</span>
                  )}
                </div>
                <div className="cn-sess-topic">
                  {s.topic.length > SESSION_TOPIC_PREVIEW_CHARS ? s.topic.slice(0, SESSION_TOPIC_PREVIEW_CHARS) + "…" : s.topic}
                </div>
                <div className="cn-sess-meta">
                  <span>{s.members.length} {t("ui.council.members", "members")}</span>
                  <span>{s.rounds} {t("ui.council.rounds_count", "rounds")}</span>
                  <span>{fmtStamp(s.created_at)}</span>
                  {s.record_id && (
                    <span className="cn-sess-record" onClick={(e) => { e.stopPropagation(); nav && nav("detail", { id: s.record_id }); }}>
                      {s.record_id}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="cn-sess-detail">
            {!selectedId && <div className="pm-empty">{t("ui.council.select_session", "Select a session to see details")}</div>}
            {selectedId && selectedError && <div className="pm-empty">{t("ui.council.session_detail_error", "Couldn't load session")}</div>}
            {selectedId && !selectedError && selectedSession && (
              <SessionDetail
                session={selectedSession}
                cancelConfirm={cancelConfirm}
                cancelling={cancelling}
                cancelErr={cancelErr}
                onCancelClick={() => setCancelConfirm(true)}
                onCancelNo={() => setCancelConfirm(false)}
                onCancelYes={onCancelYes}
                threadMessages={threadMessages}
                streamStatus={sessionStreamStatus}
                nav={nav}
              />
            )}
          </div>
        </div>
      </div>
    );
  }

  function CouncilView({ nav }) {
    const PM = window.PM;
    const [tab, setTab] = useState("board");
    const [projects, setProjects] = useState(PM.projects || []);
    const [project, setProject] = useState((PM.projects && PM.projects[0] && PM.projects[0].id) || "");
    const [thread, setThread] = useState(ALL_THREADS);
    const [threads, setThreads] = useState([]);
    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);
    const [live, setLive] = useState(true);
    const [lastUpdate, setLastUpdate] = useState(null);
    const [draft, setDraft] = useState("");
    const [draftKind, setDraftKind] = useState(COUNCIL_KINDS[0]);
    const [draftThread, setDraftThread] = useState(GENERAL_THREAD);
    const [sending, setSending] = useState(false);
    const [sendErr, setSendErr] = useState("");
    const [reloadTick, setReloadTick] = useState(0);
    const cursorRef = useRef(null);
    const inFlightRef = useRef(false);
    const threadRef = useRef(thread || null);
    const threadsRefreshTimerRef = useRef(null);

    useEffect(() => {
      if (projects.length > 0) return;
      let active = true;
      fetch("/api/projects").then((r) => (r.ok ? r.json() : { projects: [] }))
        .then((data) => {
          if (!active) return;
          const list = (data.projects || []).map((p) => ({ id: p.name, name: p.name }));
          setProjects(list);
          setProject((cur) => cur || (list[0] && list[0].id) || "");
        }).catch(() => {});
      return () => { active = false; };
    }, []);

    const onSelectProject = useCallback((next) => {
      setProject(next);
      setThread(ALL_THREADS);
      setThreads([]);
      setMessages([]);
      setLoadError(false);
      cursorRef.current = null;
    }, []);

    const onProjectChange = (e) => onSelectProject(e.target.value);

    useEffect(() => { setDraftThread(thread || GENERAL_THREAD); }, [thread]);
    useEffect(() => { threadRef.current = thread || null; }, [thread]);

    const refreshThreads = useCallback(() => {
      if (!project) { setThreads([]); return; }
      window.PM_API.fetchCouncilThreads(project).then((data) => {
        if (data.ok) setThreads(data.threads || []);
      });
    }, [project]);

    const scheduleThreadsRefresh = useCallback(() => {
      if (threadsRefreshTimerRef.current) return;
      threadsRefreshTimerRef.current = setTimeout(() => {
        threadsRefreshTimerRef.current = null;
        refreshThreads();
      }, THREADS_REFRESH_DEBOUNCE_MS);
    }, [refreshThreads]);

    useEffect(() => { refreshThreads(); }, [refreshThreads]);

    useEffect(() => () => {
      if (threadsRefreshTimerRef.current) clearTimeout(threadsRefreshTimerRef.current);
    }, []);

    useEffect(() => {
      if (!project || tab !== "board") {
        setMessages([]);
        cursorRef.current = null;
        setLoading(false);
        setLoadError(false);
        return undefined;
      }
      let active = true;
      const reqProject = project;
      const reqThread = thread || null;
      setLoading(true);
      inFlightRef.current = true;
      window.PM_API.fetchCouncilBoard(project, thread || null, null, BOARD_FETCH_LIMIT)
        .then((data) => {
          if (!active) return;
          if (!data.ok) { setLoadError(true); setLoading(false); return; }
          if (data.project !== reqProject || (data.thread || null) !== reqThread) return;
          const msgs = (data.messages || []).slice(-MAX_MESSAGES);
          setMessages(msgs);
          cursorRef.current = msgs.length > 0 ? msgs[msgs.length - 1].id : null;
          setLastUpdate(new Date());
          setLoadError(false);
          setLoading(false);
        })
        .finally(() => { inFlightRef.current = false; });
      return () => { active = false; };
    }, [project, thread, reloadTick, tab]);

    const onBoardStreamMessage = useCallback((msg) => {
      const activeThread = threadRef.current;
      if (activeThread && msg.thread !== activeThread) return;
      setMessages((prev) => mergeMessages(prev, [msg]));
      if (messageSeq(msg.id) > messageSeq(cursorRef.current)) cursorRef.current = msg.id;
      setLastUpdate(new Date());
      scheduleThreadsRefresh();
    }, [scheduleThreadsRefresh]);

    const boardStreamUrl = live && project && tab === "board" ? councilStreamUrl(project, null) : null;

    const boardStreamStatus = useCouncilStream({
      enabled: !!boardStreamUrl,
      url: boardStreamUrl,
      onMessage: onBoardStreamMessage,
      onSession: undefined,
    });

    useEffect(() => {
      if (!live || !project || tab !== "board") return undefined;
      if (boardStreamStatus !== STREAM_STATUS_POLLING) return undefined;
      let active = true;
      const reqProject = project;
      const reqThread = thread || null;
      const timer = setInterval(() => {
        if (document.hidden) return;
        if (inFlightRef.current) return;
        inFlightRef.current = true;
        window.PM_API.fetchCouncilBoard(project, thread || null, cursorRef.current, BOARD_FETCH_LIMIT)
          .then((data) => {
            if (!active) return;
            if (!data.ok) { setLoadError(true); return; }
            if (data.project !== reqProject || (data.thread || null) !== reqThread) return;
            setLoadError(false);
            const fresh = data.messages || [];
            if (fresh.length > 0) {
              setMessages((prev) => mergeMessages(prev, fresh));
              cursorRef.current = fresh[fresh.length - 1].id;
              refreshThreads();
            }
            setLastUpdate(new Date());
          })
          .finally(() => { inFlightRef.current = false; });
      }, POLL_INTERVAL_MS);
      return () => { active = false; clearInterval(timer); };
    }, [live, project, thread, refreshThreads, tab, boardStreamStatus]);

    const onSend = () => {
      if (!draft.trim() || !project || sending) return;
      const sentThread = draftThread || GENERAL_THREAD;
      setSending(true);
      setSendErr("");
      window.PM_API.postCouncilBoard({
        project,
        thread: sentThread,
        kind: draftKind,
        body: draft,
        author: "human",
        via: "human",
      }).then((res) => {
        setSending(false);
        if (res.ok) {
          setDraft("");
          if (sentThread !== thread) setThread(sentThread);
          setReloadTick((v) => v + 1);
          refreshThreads();
        } else {
          const detail = res.detail ? " — " + res.detail : "";
          setSendErr(t("ui.council.send_failed", "Send failed") + " (HTTP " + res.status + ")" + detail);
        }
      });
    };

    return (
      <div className="pm-page fade-in">
        <div className="pm-eyebrow">{t("ui.council.eyebrow", "AI Council · live board")}</div>
        <div className="cn-headrow">
          <h1 className="pm-h" style={{ marginTop: 6 }}>{t("ui.council.heading", "Council")}</h1>
          {tab === "board" && (
            <div className="cn-live">
              <button className={"cn-livebtn" + (loadError ? " err" : live ? " on" : "")} onClick={() => setLive((v) => !v)}>
                <span className="dot" /> {live ? t("ui.council.live", "Live") : t("ui.council.paused", "Paused")}
              </button>
              {live && <ConnectionIndicator status={boardStreamStatus} />}
              {lastUpdate && <span className="cn-updated">{t("ui.council.updated", "updated")} {fmtTime(lastUpdate.toISOString())}</span>}
            </div>
          )}
        </div>

        <div className="cn-tabs">
          <button className={"cn-tab" + (tab === "board" ? " on" : "")} onClick={() => setTab("board")}>{t("ui.council.tab_board", "Board")}</button>
          <button className={"cn-tab" + (tab === "sessions" ? " on" : "")} onClick={() => setTab("sessions")}>{t("ui.council.tab_sessions", "Sessions")}</button>
          <button className={"cn-tab" + (tab === "prompt" ? " on" : "")} onClick={() => setTab("prompt")}>{t("ui.council.tab_prompt", "Prompt")}</button>
        </div>

        {tab === "board" && (
          <React.Fragment>
            <div className="cn-toolbar">
              <label className="cn-field">
                <span className="l">{t("ui.council.project", "Project")}</span>
                <select className="l-sel" value={project} onChange={onProjectChange}>
                  {projects.length === 0 && <option value="">—</option>}
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
              <CouncilProjectBadge project={project} />
              <label className="cn-field">
                <span className="l">{t("ui.council.thread", "Thread")}</span>
                <select className="l-sel" value={thread} onChange={(e) => setThread(e.target.value)}>
                  <option value={ALL_THREADS}>{t("ui.council.all_threads", "All threads")}</option>
                  {threads.map((th) => <option key={th.thread} value={th.thread}>{th.thread} ({th.count})</option>)}
                </select>
              </label>
            </div>

            <div className="cn-stream">
              {loading && <div className="pm-empty">{t("ui.cand.loading", "Loading…")}</div>}
              {!loading && loadError && (
                <div className="pm-empty">
                  <div>{t("ui.council.error", "Couldn't reach the council board")}</div>
                  <div className="cn-err-hint">{t("ui.council.error_hint", "The daemon may be unreachable. It will keep retrying automatically.")}</div>
                </div>
              )}
              {!loading && !loadError && messages.length === 0 && <div className="pm-empty">{t("ui.council.empty", "No messages in this project yet")}</div>}
              {!loading && !loadError && messages.map((m) => <MessageCard key={m.id} msg={m} nav={nav} />)}
            </div>

            <div className="pm-card cn-compose">
              <textarea className="cn-textarea" value={draft} onChange={(e) => setDraft(e.target.value)}
                placeholder={t("ui.council.placeholder", "Write a note for the council…")} spellCheck={false} />
              <div className="cn-composebar">
                <select className="l-sel" value={draftKind} onChange={(e) => setDraftKind(e.target.value)}>
                  {COUNCIL_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
                <input className="cn-threadinput" value={draftThread} onChange={(e) => setDraftThread(e.target.value)} placeholder={GENERAL_THREAD} />
                <button className="pm-btn accent" disabled={!draft.trim() || sending || !project} onClick={onSend}>
                  <Icon name="arrowRight" size={14} /> {t("ui.council.send", "Send")}
                </button>
              </div>
              {sendErr && <div className="cn-err">{sendErr}</div>}
            </div>
          </React.Fragment>
        )}

        {tab === "sessions" && <SessionsPanel project={project} onSelectProject={onSelectProject} nav={nav} />}

        {tab === "prompt" && (window.PMCouncilPrompt ? <window.PMCouncilPrompt project={project} nav={nav} /> : null)}
      </div>
    );
  }

  window.PMCouncil = CouncilView;
})();
