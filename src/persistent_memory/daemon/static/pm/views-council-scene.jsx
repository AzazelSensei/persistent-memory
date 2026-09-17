// persistent-memory — AI Council: pixel-art council table, "who is speaking right now".
(function () {
  const React = window.React;
  const { useState, useEffect, useRef } = React;

  const GRID_W = 12;
  const GRID_H = 18;
  const AVATAR_W_PX = 48;
  const AVATAR_H_PX = 72;
  const BUBBLE_PREVIEW_CHARS = 96;
  const LAST_WORD_PREVIEW_CHARS = 200;
  const HIGHLIGHT_DURATION_MS = 300;
  const MISSING_TURN_STATUS = "—";

  const TERMINAL_SESSION_STATUSES = ["converged", "failed", "cancelled"];

  const CLAUDE_HEAD = [
    "000111111000",
    "001111111100",
    "011111111110",
    "111111111111",
    "111011111011",
    "111011111011",
    "111111111111",
    "111100001111",
    "111111111111",
    "011111111110",
    "001111111100",
    "000111111000",
  ];
  const CODEX_HEAD = [
    "000011110000",
    "001111111100",
    "011111111110",
    "110000000011",
    "110000000011",
    "110111111011",
    "110000000011",
    "110000000011",
    "011111111110",
    "001111111100",
    "000011110000",
    "000011110000",
  ];
  const GROK_HEAD = [
    "000001100000",
    "000011110000",
    "000111111000",
    "001111111100",
    "011110011110",
    "111100001111",
    "111100001111",
    "011110011110",
    "001111111100",
    "000111111000",
    "000011110000",
    "000001100000",
  ];
  const KIMI_HEAD = [
    "000011110000",
    "000111111000",
    "001111111100",
    "011111000000",
    "011110000000",
    "111100000000",
    "111100000000",
    "011110000000",
    "011111000000",
    "001111111100",
    "000111111000",
    "000011110000",
  ];
  const GENERIC_HEAD = [
    "000001100000",
    "000011110000",
    "000111111000",
    "001111111100",
    "011111111110",
    "111111111111",
    "111111111111",
    "011111111110",
    "001111111100",
    "000111111000",
    "000011110000",
    "000001100000",
  ];

  const SHOULDERS = [
    "000011110000",
    "000111111000",
    "011111111110",
    "111111111111",
    "111111111111",
    "111111111111",
  ];

  const MEMBER_STATUS_WAITING = "waiting";
  const MEMBER_STATUS_THINKING = "thinking";
  const MEMBER_STATUS_SPEAKING = "speaking";
  const MEMBER_STATUS_DONE = "done";
  const MEMBER_STATUS_TIMEOUT = "timeout";
  const MEMBER_STATUS_FAILED = "failed";
  const MEMBER_STATUS_SKIPPED = "skipped";

  const MEMBER_STATUS_COLOR = {
    [MEMBER_STATUS_WAITING]: "var(--faint)",
    [MEMBER_STATUS_THINKING]: "var(--violet)",
    [MEMBER_STATUS_SPEAKING]: "var(--accent-ink)",
    [MEMBER_STATUS_DONE]: "var(--st-accepted)",
    [MEMBER_STATUS_TIMEOUT]: "var(--st-proposed)",
    [MEMBER_STATUS_FAILED]: "var(--st-reverted)",
    [MEMBER_STATUS_SKIPPED]: "var(--dim)",
  };

  const MEMBER_STATUS_MARK = {
    [MEMBER_STATUS_WAITING]: "○",
    [MEMBER_STATUS_THINKING]: "⋯",
    [MEMBER_STATUS_SPEAKING]: "●",
    [MEMBER_STATUS_DONE]: "✓",
    [MEMBER_STATUS_TIMEOUT]: "⏱",
    [MEMBER_STATUS_FAILED]: "✗",
    [MEMBER_STATUS_SKIPPED]: "—",
  };

  const MEMBER_STATUS_I18N = {
    [MEMBER_STATUS_WAITING]: ["ui.council.scene.waiting", "Waiting"],
    [MEMBER_STATUS_THINKING]: ["ui.council.scene.thinking", "Thinking"],
    [MEMBER_STATUS_SPEAKING]: ["ui.council.scene.speaking", "Speaking"],
    [MEMBER_STATUS_DONE]: ["ui.council.scene.done", "Done"],
    [MEMBER_STATUS_TIMEOUT]: ["ui.council.scene.timeout", "Timed out"],
    [MEMBER_STATUS_FAILED]: ["ui.council.scene.failed", "Failed"],
    [MEMBER_STATUS_SKIPPED]: ["ui.council.scene.skipped", "Skipped"],
  };

  const CELL_TERMINAL_STATUSES = new Set([
    "done", "skipped", "failed", "timeout", "cancelled", MISSING_TURN_STATUS,
  ]);

  const MARKDOWN_NOISE_RE = /[*_`#>|]+/g;
  const MULTISPACE_RE = /\s+/g;

  if (!document.getElementById("pm-council-scene-css")) {
    const s = document.createElement("style");
    s.id = "pm-council-scene-css";
    s.textContent = `
.cns-scene{padding:16px 18px;margin-top:18px;overflow:hidden}
.cns-progress{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.cns-progress-label{font-family:var(--font-mono);font-size:11px;letter-spacing:.5px;color:var(--dim);text-transform:uppercase}
.cns-dots{display:flex;align-items:center;gap:6px}
.cns-dot{width:8px;height:8px;background:transparent;border:1.5px solid var(--line2);box-sizing:border-box;display:inline-block}
.cns-dot.done{background:var(--st-accepted);border-color:var(--st-accepted)}
.cns-dot.active{background:var(--violet);border-color:var(--violet);animation:cns-pulse 1.2s ease-in-out infinite}
.cns-dot.synth{transform:rotate(45deg)}
.cns-stage{position:relative;margin-top:20px;padding-bottom:6px}
.cns-members{display:flex;gap:18px;flex-wrap:wrap;justify-content:center;align-items:flex-end;position:relative;z-index:1}
.cns-member{display:flex;flex-direction:column;align-items:center;width:150px;text-align:center;position:relative}
.cns-bubble{position:relative;margin-bottom:14px;padding:7px 9px;border:2px solid var(--accent-line);background:var(--accent-soft);font-size:11px;color:var(--txt);text-align:left;line-height:1.45;width:100%;box-sizing:border-box}
.cns-bubble::after{content:"";position:absolute;left:calc(50% - 7px);bottom:-6px;width:12px;height:6px;background:var(--accent-soft);border-left:2px solid var(--accent-line);border-right:2px solid var(--accent-line)}
.cns-bubble::before{content:"";position:absolute;left:calc(50% - 3px);bottom:-12px;width:4px;height:6px;background:var(--accent-soft);border-left:2px solid var(--accent-line);border-right:2px solid var(--accent-line);border-bottom:2px solid var(--accent-line);z-index:1}
.cns-bubble.flash{animation:cns-flash 300ms ease-out}
.cns-avatar-wrap{position:relative;display:inline-flex;padding:3px}
.cns-avatar-wrap.waiting,.cns-avatar-wrap.skipped{opacity:.35}
.cns-avatar-wrap.speaking{filter:drop-shadow(0 0 6px var(--accent-ink))}
.cns-avatar-svg{display:block;image-rendering:pixelated;image-rendering:crisp-edges}
.cns-avatar-wrap.thinking .cns-avatar-svg{animation:cns-pulse 1.4s ease-in-out infinite}
.cns-spoke-badge{position:absolute;top:-4px;right:8px;font-size:13px;color:var(--st-proposed);line-height:1}
.cns-seat{height:26px;width:100%}
.cns-plate{height:36px;display:flex;flex-direction:column;align-items:center;gap:3px;justify-content:flex-start}
.cns-member-name{font-family:var(--font-mono);font-size:11.5px;color:var(--txt-hi);font-weight:600}
.cns-member-status{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--dim)}
.cns-member-status .mark{font-family:var(--font-mono)}
.cns-member-status.timeout{color:var(--st-proposed)}
.cns-member-status.failed{color:var(--st-reverted)}
.cns-member-status.done{color:var(--st-accepted)}
.cns-member-status.speaking{color:var(--accent-ink)}
.cns-table{position:absolute;left:-18px;right:-18px;bottom:42px;height:26px;z-index:2;background:var(--panel-hi);border-top:4px solid var(--line2);border-bottom:2px solid var(--line);background-image:repeating-linear-gradient(90deg,transparent 0 10px,color-mix(in srgb, var(--line2) 22%, transparent) 10px 12px)}
.cns-lastword{margin-top:16px;padding:12px 14px;border:1px solid var(--line);background:var(--panel-hi)}
.cns-lastword-head{font-family:var(--font-mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--faint)}
.cns-lastword-body{margin-top:6px;font-size:12.5px;color:var(--txt);line-height:1.5}
@keyframes cns-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.55;transform:scale(1.1)}}
@keyframes cns-flash{0%{box-shadow:0 0 0 0 var(--accent-line)}100%{box-shadow:0 0 0 7px transparent}}
@media (prefers-reduced-motion: reduce){
  .cns-dot.active{animation:none}
  .cns-avatar-wrap.thinking .cns-avatar-svg{animation:none}
  .cns-bubble.flash{animation:none}
}
`;
    document.head.appendChild(s);
  }

  function resolveHeadPattern(memberId) {
    const id = String(memberId || "").toLowerCase();
    if (id.indexOf("claude") >= 0) return CLAUDE_HEAD;
    if (id.indexOf("codex") >= 0) return CODEX_HEAD;
    if (id.indexOf("grok") >= 0) return GROK_HEAD;
    if (id.indexOf("kimi") >= 0) return KIMI_HEAD;
    return GENERIC_HEAD;
  }

  function isSessionLive(session) {
    return TERMINAL_SESSION_STATUSES.indexOf(session.status) < 0;
  }

  function deriveMemberStatus(cell, lastMessage, live) {
    if (!cell) return MEMBER_STATUS_WAITING;
    if (cell.status === "pending" || cell.status === MISSING_TURN_STATUS) return MEMBER_STATUS_WAITING;
    if (cell.status === "running") return MEMBER_STATUS_THINKING;
    if (cell.status === "timeout") return MEMBER_STATUS_TIMEOUT;
    if (cell.status === "failed") return MEMBER_STATUS_FAILED;
    if (cell.status === "skipped" || cell.status === "cancelled") return MEMBER_STATUS_SKIPPED;
    if (cell.status === "done") {
      if (!live) return MEMBER_STATUS_DONE;
      if (lastMessage && cell.message_id && cell.message_id === lastMessage.id) return MEMBER_STATUS_SPEAKING;
      return MEMBER_STATUS_DONE;
    }
    return MEMBER_STATUS_WAITING;
  }

  function isRoundStarted(cells) {
    return cells.some((c) => c.status !== "pending" && c.status !== MISSING_TURN_STATUS);
  }

  function isRoundComplete(cells) {
    return cells.every((c) => CELL_TERMINAL_STATUSES.has(c.status));
  }

  function computeCurrentRound(matrix) {
    for (let i = matrix.rounds.length - 1; i >= 0; i--) {
      if (isRoundStarted(matrix.rounds[i].cells)) return matrix.rounds[i].round;
    }
    return matrix.rounds.length > 0 ? matrix.rounds[0].round : 1;
  }

  function isSynthesisPhase(matrix, live) {
    if (matrix.rounds.length === 0) return false;
    if (!matrix.rounds.every((row) => isRoundComplete(row.cells))) return false;
    if (live) return true;
    return !!matrix.synthesis && matrix.synthesis.status !== "pending";
  }

  function resolveSynthesisAuthor(matrix, session) {
    if (matrix.synthesis && matrix.synthesis.member_id) return matrix.synthesis.member_id;
    return session.spokesperson;
  }

  function resolveMemberCell(memberId, matrix, session, currentRound, synthesisPhase) {
    if (synthesisPhase) {
      if (memberId === resolveSynthesisAuthor(matrix, session)) {
        return matrix.synthesis || { round: session.rounds + 1, member_id: memberId, status: "pending", message_id: null };
      }
      const lastRow = matrix.rounds[matrix.rounds.length - 1];
      return lastRow.cells.find((c) => c.member_id === memberId) || null;
    }
    const row = matrix.rounds.find((r) => r.round === currentRound);
    if (!row) return null;
    return row.cells.find((c) => c.member_id === memberId) || null;
  }

  function findSpeakingMemberId(sceneState) {
    const { session, matrix, currentRound, synthesisPhase, lastMessage, live } = sceneState;
    if (!lastMessage) return null;
    const speaker = session.members.find((memberId) => {
      const cell = resolveMemberCell(memberId, matrix, session, currentRound, synthesisPhase);
      return deriveMemberStatus(cell, lastMessage, live) === MEMBER_STATUS_SPEAKING;
    });
    return speaker || null;
  }

  function roundDotStatus(cells) {
    if (isRoundComplete(cells)) return "done";
    if (isRoundStarted(cells)) return "active";
    return "pending";
  }

  function synthesisDotStatus(matrix, synthesisPhase) {
    if (!synthesisPhase) return "pending";
    const synthesis = matrix.synthesis;
    if (!synthesis || synthesis.status === "pending" || synthesis.status === "running") return "active";
    return "done";
  }

  function plainPreview(body, limit) {
    const text = String(body || "").replace(MARKDOWN_NOISE_RE, " ").replace(MULTISPACE_RE, " ").trim();
    return text.length > limit ? text.slice(0, limit) + "…" : text;
  }

  function PixelAvatar({ memberId, color, ariaLabel }) {
    const head = resolveHeadPattern(memberId);
    const rects = [];
    const paint = (row, y) => {
      for (let x = 0; x < row.length; x++) {
        if (row[x] === "1") rects.push(<rect key={x + "-" + y} x={x} y={y} width="1" height="1" />);
      }
    };
    head.forEach((row, y) => paint(row, y));
    SHOULDERS.forEach((row, y) => paint(row, head.length + y));
    return (
      <svg
        className="cns-avatar-svg"
        width={AVATAR_W_PX}
        height={AVATAR_H_PX}
        viewBox={"0 0 " + GRID_W + " " + GRID_H}
        shapeRendering="crispEdges"
        style={{ fill: color }}
        role="img"
        aria-label={ariaLabel}
      >
        {rects}
      </svg>
    );
  }

  function MemberCard({ memberId, cell, isSpokesperson, lastMessage, live }) {
    const status = deriveMemberStatus(cell, lastMessage, live);
    const color = MEMBER_STATUS_COLOR[status];
    const mark = MEMBER_STATUS_MARK[status];
    const statusLabel = t(MEMBER_STATUS_I18N[status][0], MEMBER_STATUS_I18N[status][1]);
    const speaking = status === MEMBER_STATUS_SPEAKING && !!lastMessage;
    const prevSpeakingMsgIdRef = useRef(null);
    const [flash, setFlash] = useState(false);

    useEffect(() => {
      if (!speaking) return undefined;
      if (prevSpeakingMsgIdRef.current === lastMessage.id) return undefined;
      prevSpeakingMsgIdRef.current = lastMessage.id;
      setFlash(true);
      const timer = setTimeout(() => setFlash(false), HIGHLIGHT_DURATION_MS);
      return () => clearTimeout(timer);
    }, [speaking, lastMessage]);

    return (
      <div className="cns-member">
        {speaking && (
          <div className={"cns-bubble" + (flash ? " flash" : "")}>
            {plainPreview(lastMessage.body, BUBBLE_PREVIEW_CHARS)}
          </div>
        )}
        <div className={"cns-avatar-wrap " + status}>
          <PixelAvatar memberId={memberId} color={color} ariaLabel={memberId + " — " + statusLabel} />
          {isSpokesperson && (
            <span className="cns-spoke-badge" title={t("ui.council.scene.spokesperson", "Spokesperson")}>★</span>
          )}
        </div>
        <div className="cns-seat" />
        <div className="cns-plate">
          <div className="cns-member-name">{memberId}</div>
          <div className={"cns-member-status " + status}>
            <span className="mark">{mark}</span>
            <span>{statusLabel}</span>
          </div>
        </div>
      </div>
    );
  }

  function RoundProgress({ matrix, session, currentRound, synthesisPhase }) {
    const roundLabel = t("ui.council.scene.round_progress", "Round").toUpperCase();
    const synthesisLabel = t("ui.council.scene.synthesis", "Synthesis");
    return (
      <div className="cns-progress">
        <span className="cns-progress-label">
          {synthesisPhase ? synthesisLabel.toUpperCase() : roundLabel + " " + currentRound + " / " + session.rounds}
        </span>
        <div className="cns-dots">
          {matrix.rounds.map((row) => (
            <span
              key={row.round}
              className={"cns-dot " + roundDotStatus(row.cells)}
              title={roundLabel + " " + row.round}
            />
          ))}
          <span
            className={"cns-dot synth " + synthesisDotStatus(matrix, synthesisPhase)}
            title={synthesisLabel}
          />
        </div>
      </div>
    );
  }

  function LastWordPanel({ lastMessage }) {
    if (!lastMessage) return null;
    return (
      <div className="cns-lastword">
        <div className="cns-lastword-head">{t("ui.council.scene.last_word", "Last word")} — {lastMessage.author}</div>
        <div className="cns-lastword-body">"{plainPreview(lastMessage.body, LAST_WORD_PREVIEW_CHARS)}"</div>
      </div>
    );
  }

  function CouncilScene({ session, matrix, threadMessages }) {
    if (!session || !matrix) {
      return (
        <figure className="pm-card cns-scene">
          <div className="pm-empty">{t("ui.council.scene.no_active_session", "No active session to show")}</div>
        </figure>
      );
    }

    const live = isSessionLive(session);
    const currentRound = computeCurrentRound(matrix);
    const synthesisPhase = isSynthesisPhase(matrix, live);
    const lastMessage = threadMessages && threadMessages.length > 0 ? threadMessages[threadMessages.length - 1] : null;
    const speakingMemberId = findSpeakingMemberId({
      session, matrix, currentRound, synthesisPhase, lastMessage, live,
    });

    return (
      <figure className="pm-card cns-scene">
        <RoundProgress matrix={matrix} session={session} currentRound={currentRound} synthesisPhase={synthesisPhase} />
        <div className="cns-stage">
          <div className="cns-members">
            {session.members.map((memberId) => (
              <MemberCard
                key={memberId}
                memberId={memberId}
                cell={resolveMemberCell(memberId, matrix, session, currentRound, synthesisPhase)}
                isSpokesperson={memberId === session.spokesperson}
                lastMessage={lastMessage}
                live={live}
              />
            ))}
          </div>
          <div className="cns-table" aria-hidden="true" />
        </div>
        {speakingMemberId === null && <LastWordPanel lastMessage={lastMessage} />}
      </figure>
    );
  }

  window.PMCouncilScene = CouncilScene;
})();
